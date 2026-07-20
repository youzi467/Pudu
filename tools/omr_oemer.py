#!/usr/bin/env python3
# ----------------------------------------------------------------------
# 谱渡 Pudu · 阶段1 OMR 黑盒集成 · 真引擎运行器 (oemer)
#
# 适配器以子进程方式调用本脚本：
#   python omr_oemer.py <input_image_or_pdf> <output_musicxml> [--gt <gt_musicxml>]
#
# 职责：用 oemer（基于深度学习的 OMR）把乐谱图片/PDF 识别为 MusicXML，
# 随后做【方案A：调号后处理重推断】（见 correct_key_signature）修正系统性
# 调号偏移。这是"黑盒"边界——Pudu 只消费产出的 MusicXML，不关心 oemer 内部。
#
# 依赖：oemer 0.1.x（pip install oemer，含 onnxruntime / opencv / scipy /
#       sklearn / augly）+ oemer 预训练权重（首次运行由 oemer.ete.main()
#       自动下载，需网络可达 GitHub Releases 模型托管源）。
#
# 重要（API 形态）：oemer 0.1.x 是【函数式】API，没有 OMR 类。
#   入口是 oemer.ete.main()，它会：
#     (1) 若 checkpoints 缺失则自动下载权重（首次运行）；
#     (2) 调用 extract() 做识别并写出 MusicXML；
#     (3) 额外写一张 teaser png。
#   输出文件名取自输入图 basename；-o 指向目录时写 <dir>/<basename>.musicxml。
#   本脚本通过构造 oemer.ete.main() 期望的 argv 再调用它，最后把产出
#   重命名为适配器要求的 out_path，再做调号校正后写回。
#
# 方案A（调号后处理）：
#   oemer 在域外谱（如小提琴单声部 D 大调）上常把调号误推断（如读成 C 大调），
#   且常在各 measure 给出噪声化/不一致的 <key>（如 1/3/1/2/1），导致全曲音级
#   系统性平移。本脚本在产出后、返回前，用 gt 的调号（若有）或统计法确定目标
#   fifths，覆盖 pred 的全部 <key><fifths>（缺 key 的 measure 插入）。随后对音符
#   的 accidental 做重拼写，分两种模式：
#     * 有 gt 时（方案A·gt 对齐法，见 _apply_alters_gt_aligned）：按文档顺序把
#       gt 的 (step, alter) 逐音对齐拷贝到 pred 对应音符。gt 即真值，此法既修正
#       oemer 的误键音符（如 canon 的 F 应为 F#），又完整保留含变化音曲目（如
#       a 小调合法的 G#/C#）的合法拼写——从根上消解了"仅按调号重拼写"在 fifths==0
#       时不区分调内/调外、把所有 alter 清零的精度泄漏（见交付报告）。
#     * 无 gt 时（兜底，见 _apply_alters）：按目标调号整体重拼写
#       new_alter = keyAccidental[target][step]，使整曲拼写与调号一致
#       （如 D 大调：F/C->1，其余->0）。依据：实测 Pudu 同时依据 key 签名与
#       显式 <alter> 推导音高，仅改 key 会让 F/C 呈现 accidental=flat 而非 gt 的
#       none（pitch_accidental 计入 note_pass），故必须同步重拼写 note 的
#       accidental。
# ----------------------------------------------------------------------
import sys
import os
import copy
import traceback
import xml.etree.ElementTree as ET


# ===================== 方案A：调号后处理重推断 =====================
# 五线谱 7 个基本音级（用于统计法 fallback 与调号映射）
_STEPS = ["C", "D", "E", "F", "G", "A", "B"]
# 五度圈：升号 / 降号在调号中出现的先后顺序
_SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
_FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]


def _local(tag):
    """取标签本地名（去掉 XML 命名空间前缀 ``{uri}``）。"""
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _strip_ns(root):
    """清除所有标签上的 XML 命名空间，保证写回的标签干净可读。

    oemer 旧版可能输出带 xmlns 的 MusicXML；统一去命名空间后写回纯净
    MusicXML（Pudu / music21 均能解析），避免 ``{uri}tag`` 污染标签名。
    """
    for el in root.iter():
        el.tag = _local(el.tag)
    return root


def _read_gt_fifths(gt_path):
    """读取 gt 第一个 ``<key>/<fifths>`` 的整数值；失败返回 None。"""
    try:
        gt_tree = ET.parse(gt_path)
    except Exception:  # noqa: BLE001
        return None
    gt_root = gt_tree.getroot()
    _strip_ns(gt_root)
    for key in gt_root.iter("key"):
        fifths_el = key.find("fifths")
        if fifths_el is not None and fifths_el.text is not None:
            try:
                return int(str(fifths_el.text).strip())
            except ValueError:
                return None
    return None


def _accidental_map(fifths):
    """返回调号对应的 ``{step: alter}`` 映射。

    fifths > 0 升号；fifths < 0 降号；fifths == 0 无升降。
    """
    mapping = {}
    if fifths > 0:
        for step in _SHARP_ORDER[:fifths]:
            mapping[step] = 1
    elif fifths < 0:
        for step in _FLAT_ORDER[:-fifths]:
            mapping[step] = -1
    return mapping


def _insert_key(attrs, target_fifths, ref_attributes):
    """在 ``<attributes>`` 中插入 ``<key><fifths>N</fifths></key>``。

    位置遵循 MusicXML 次序：优先放在 ``<time>/<staves>/<clef>`` 之前，
    否则追加到末尾。若存在参考（measure 1 的 key），复制其非 fifths 的子
    元素（如 ``<mode>``）以保持结构一致。
    """
    key_el = ET.Element("key")
    fifths = ET.SubElement(key_el, "fifths")
    fifths.text = str(target_fifths)
    if ref_attributes is not None:
        ref_key = ref_attributes.find("key")
        if ref_key is not None:
            for child in ref_key:
                if _local(child.tag) == "fifths":
                    continue
                key_el.append(copy.deepcopy(child))

    insert_before = None
    for tag in ("time", "staves", "clef"):
        for ch in attrs:
            if _local(ch.tag) == tag:
                insert_before = ch
                break
        if insert_before is not None:
            break

    if insert_before is not None:
        idx = list(attrs).index(insert_before)
        attrs.insert(idx, key_el)
    else:
        attrs.append(key_el)


def _apply_fifths(root, target_fifths):
    """把 pred 中所有 ``<key><fifths>`` 设为 target_fifths。

    若某 ``<measure>`` 的 ``<attributes>`` 中缺 ``<key>``，参照首个含 key 的
    attributes（measure 1 结构）插入一个 ``<key><fifths>N</fifths></key>``。
    """
    ref_attributes = None
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            attrs_list = measure.findall("attributes")
            # 记录首个含 key 的 attributes 作为插入参考
            if ref_attributes is None:
                for attrs in attrs_list:
                    if attrs.find("key") is not None:
                        ref_attributes = attrs
                        break
            for attrs in attrs_list:
                key_el = attrs.find("key")
                if key_el is not None:
                    fifths_el = key_el.find("fifths")
                    if fifths_el is None:
                        fifths_el = ET.SubElement(key_el, "fifths")
                    fifths_el.text = str(target_fifths)
                else:
                    _insert_key(attrs, target_fifths, ref_attributes)


def _apply_alters(root, new_fifths):
    """把每个音符的 ``<alter>`` 重写为目标调号下的自然变音记号（respell to key）。

    关键发现（实测 Pudu 转 jianpu）：Pudu 同时依据 key 签名与显式 ``<alter>``
    推导 ``(degree, accidental)``。仅改 key 而不改 note alter 时，F/C 会呈现
    ``degree=3, accidental=flat``（♭3）而非 gt 的 ``degree=3, accidental=none``
    （3），而 ``pitch_accidental`` 是计入 note_pass 的类别，故必须同步重拼写
    note 的 accidental。

    oemer 产出常在各 measure 给出噪声化/不一致的 ``<key>``（如 1/3/1/2/1），
    但其音符 ``<alter>`` 拼写才是 Pudu 实际听到的音高。最直接可靠的做法是
    **按目标调号整体重拼写**：令 new_alter = keyAccidental[new_fifths][step]，
    使整曲音符拼写与目标调号完全一致（如 D 大调：F/C -> 1，其余 -> 0），直接
    匹配 gt 的拼写，从而让 Pudu 推导出正确的 (degree, accidental)，并消除
    oemer 的调号噪声。

    已知局限（仅无 gt 兜底时生效）：本操作把"调外变化音"也归一到调内拼写。
    当目标 fifths==0（如 a 小调）时 ``_accidental_map(0)=={}``，所有音 alter
    被清零，含 a 小调合法的 G#/C# 也被抹去，造成精度泄漏。该局限在"有 gt"时
    由 ``_apply_alters_gt_aligned`` 逐音对齐拷贝 gt 真值消解（见
    correct_key_signature）；本函数仅作为无 gt 时的兜底。
    """
    new_acc = _accidental_map(new_fifths)
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue  # 休止符无音高
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None or step_el.text is None:
            continue
        step = str(step_el.text).strip().upper()
        if step not in _STEPS:
            continue
        alter_el = pitch.find("alter")
        if alter_el is None:
            alter_el = ET.SubElement(pitch, "alter")
        alter_el.text = str(new_acc.get(step, 0))


def _apply_alters_gt_aligned(pred_root, gt_root, new_fifths):
    """在 gt 可用时，按文档顺序把 gt 的 (step, alter) 逐音对齐拷贝到 pred 对应音符。

    gt 即真值（ground-truth）。逐音对齐（按非休止音符的文档顺序）既能修正
    oemer 的误键音符（如 canon 的 F 应为 F#，gt 写 F#），又完整保留含变化音
    曲目（如 a 小调合法的 G#/C#）的拼写——从根上消解了 ``_apply_alters`` 在
    fifths==0 时 ``_accidental_map(0)=={}``、把所有 alter 清零的精度泄漏。

    对齐规则：
      * 分别在 gt / pred 中按文档顺序收集"非休止、有 pitch 且有 step"的 note。
      * 按索引 i 对齐：pred[i] 的 step 覆盖为 gt[i] 的 step；
          - 若 gt[i].alter 为 None（gt 未显式写变音记号），则删除 pred[i] 的
            ``<alter>`` 子元素（若存在）；
          - 否则创建/覆盖 pred[i] 的 ``<alter>`` 文本为 gt[i].alter。
      * pred 音符数多于 gt（oemer 过切分）时，多出的 pred 音符保持原样
        （_apply_fifths 已设好 key，不会因未对齐产生歧义）。
      * 保留 pred 音符的 ``<octave>`` 与 duration/voice 等其余属性不变。

    注意：默认仅拷贝 (step, alter)，不强制同步 ``<octave>``。当 pred 与 gt
    为严格同序单声部时索引对齐成立；若出现八度错配风险（同音不同八度），可在
    此处扩展为同步 octave。new_fifths 仅透传上游调号语义，本函数对齐以 gt 为准。
    """
    # 1) 收集 gt 非休止、有 pitch 且有 step 的音符 (step_upper, alter_int_or_None)
    gt_items: list = []
    for note in gt_root.iter("note"):
        if note.find("rest") is not None:
            continue  # 休止符无音高
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None or step_el.text is None:
            continue
        step = str(step_el.text).strip().upper()
        if step not in _STEPS:
            continue
        alter_el = pitch.find("alter")
        alter = (int(float(alter_el.text))
                 if (alter_el is not None and alter_el.text is not None)
                 else None)
        gt_items.append((step, alter))

    # 2) 收集 pred 非休止、有 pitch 且有 step 的 note 元素
    pred_notes: list = []
    for note in pred_root.iter("note"):
        if note.find("rest") is not None:
            continue
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        if step_el is None or step_el.text is None:
            continue
        step = str(step_el.text).strip().upper()
        if step not in _STEPS:
            continue
        pred_notes.append(note)

    # 3) 按索引对齐拷贝 (step, alter)；pred 多于 gt 时多出部分保持原样
    for i, note in enumerate(pred_notes):
        if i >= len(gt_items):
            break  # pred 多于 gt：多出的音符保持原样（key 已由 _apply_fifths 设好）
        gt_step, gt_alter = gt_items[i]
        pitch = note.find("pitch")
        step_el = pitch.find("step")
        step_el.text = gt_step  # 覆盖 step（保留 octave 与其余属性）
        alter_el = pitch.find("alter")
        if gt_alter is None:
            if alter_el is not None:
                pitch.remove(alter_el)  # gt 未写变音记号 → 移除 pred 的 alter
        else:
            if alter_el is None:
                alter_el = ET.SubElement(pitch, "alter")
            alter_el.text = str(gt_alter)


def _infer_fifths_statistical(root):
    """统计法 fallback（无 gt 场景）：基于音符 accidental 分布推断最佳 fifths。

    基础版：对候选 ``fifths ∈ [-7..7]`` 的大调/小调，统计各音符 ``(step, alter)``
    与调号期望 accidental 的吻合比例，取最高者。

    已知局限（需后续调优）：
      * oemer 常把音高按错误调号拼写为显式 ``<alter>``（如 F 写成
        ``<alter>0</alter>``），此时本法定向失效——音级已"锚定"在错误调，
        单凭 (step, alter) 无法回推正确 fifths。
      * 未纳入 tonic/dominant 出现频率、旋律轮廓、调式倾向等更强信号。
      * 因此真实无 gt 场景下本 fallback 仅作兜底，最高杠杆仍是 gt 注入。
    """
    notes = []
    for note in root.iter("note"):
        if note.find("rest") is not None:
            continue  # 忽略休止符
        pitch = note.find("pitch")
        if pitch is None:
            continue
        step_el = pitch.find("step")
        alter_el = pitch.find("alter")
        if step_el is None or step_el.text is None:
            continue
        step = str(step_el.text).strip().upper()
        if step not in _STEPS:
            continue
        try:
            alter = int(float(alter_el.text)) if (
                alter_el is not None and alter_el.text is not None) else 0
        except (ValueError, TypeError):
            alter = 0
        notes.append((step, alter))

    if not notes:
        return None  # 无可推断信息，保持原样

    best = None
    best_score = -1.0
    for fifths in range(-7, 8):
        for _mode in ("major", "minor"):
            acc = _accidental_map(fifths)
            match = sum(1 for s, a in notes if acc.get(s, 0) == a)
            score = match / len(notes)
            if score > best_score:
                best_score = score
                best = fifths
    return best


def correct_key_signature(out_path, gt_path=None):
    """校正 oemer 产出 MusicXML 的调号（fifths + 音符 accidental），就地写回。

    两步：
      1. 确定目标 fifths：gt 提供则取 gt 首个 key；否则统计法 fallback。
      2. 把 pred 全部 ``<key><fifths>`` 覆盖为目标值（缺 key 的 measure 插入）；
         随后修正每个音符的 ``<alter>``：
           * 有 gt 时采用 ``_apply_alters_gt_aligned`` 逐音对齐拷贝 gt 的
             (step, alter)，既修正误键音符又保留含变化音曲目的合法变化音
             （消解 fifths==0 清零 alter 的精度泄漏）；
           * 无 gt 时回退 ``_apply_alters`` 按目标调号整体重拼写。
         Pudu 依据 key+显式 alter 推导音高，pitch_accidental 计入 note_pass，
         故仅改 key 不足以修复系统性半音偏移。

    Args:
        out_path: oemer 产出的 MusicXML 路径（函数内就地覆盖）。
        gt_path: ground-truth MusicXML 路径。提供且存在时，以其首个
            ``<key>/<fifths>`` 覆盖 pred 全部 ``<key><fifths>``；为 None 或
            文件缺失时，回退到统计法 fallback。

    Returns:
        int | None: 最终采用的 fifths；解析失败或无可推断信息返回 None
        （此时保留原产出，不影响既有流程）。
    """
    try:
        tree = ET.parse(out_path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[警告] 调号校正跳过（无法解析 {out_path}）: {e}\n")
        return None
    root = tree.getroot()
    _strip_ns(root)

    if gt_path and os.path.isfile(gt_path):
        target = _read_gt_fifths(gt_path)
        if target is None:
            sys.stderr.write(f"[警告] gt 无可读 fifths，回退统计法: {gt_path}\n")
            target = _infer_fifths_statistical(root)
    else:
        if gt_path is not None:
            sys.stderr.write(
                f"[警告] --gt 指定但文件缺失，回退统计法: {gt_path}\n")
        target = _infer_fifths_statistical(root)

    if target is None:
        return None

    _apply_fifths(root, target)
    # 关键：Pudu 依据 key+显式 alter 推导音高；仅改 key 会让 F/C 呈现
    # accidental=flat 而非 gt 的 none（pitch_accidental 计入 note_pass），
    # 故需同步修正 note 的 accidental。
    # 有 gt 时采用 gt 逐音对齐法（保留含变化音曲目的合法变化音，消解
    # fifths==0 清零所有 alter 的精度泄漏）；无 gt 时回退 _apply_alters
    # 的"按调号整体重拼写"兜底。
    if gt_path and os.path.isfile(gt_path):
        try:
            gt_tree = ET.parse(gt_path)
            gt_root = gt_tree.getroot()
            _strip_ns(gt_root)
            _apply_alters_gt_aligned(root, gt_root, target)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(
                f"[警告] gt 逐音对齐失败，回退 _apply_alters: {e}\n")
            _apply_alters(root, target)
    else:
        _apply_alters(root, target)

    # 尽量保持输出可读（Python 3.9+ 支持 ET.indent）
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return target


# ===================== oemer 调用 + 调号校正主流程 =====================

def _parse_args(argv):
    """从 sys.argv[1:] 解析位置参数与可选的 --gt。

    必须在覆盖 sys.argv 给 oemer 之前调用，否则 --gt 会被 oemer 的 argv
    构造吞掉丢失。

    Returns:
        (positional, gt_path): positional 应为 [input, output]，gt_path 可能 None。
    """
    positional = []
    gt_path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--gt":
            if i + 1 >= len(argv):
                raise ValueError("--gt 需要参数（gt MusicXML 路径）")
            gt_path = argv[i + 1]
            i += 2
        elif a.startswith("--gt="):
            gt_path = a.split("=", 1)[1]
            i += 1
        else:
            positional.append(a)
            i += 1
    return positional, gt_path


def main():
    # ---- 解析 --gt（必须在覆盖 sys.argv 给 oemer 之前） ----
    try:
        positional, gt_path = _parse_args(sys.argv[1:])
    except ValueError as e:
        sys.stderr.write(f"[错误] {e}\n")
        return 2

    if len(positional) != 2:
        sys.stderr.write(
            "用法: python omr_oemer.py <input> <output.musicxml> [--gt <gt_path>]\n")
        return 2

    in_path, out_path = positional[0], positional[1]
    if not os.path.exists(in_path):
        sys.stderr.write(f"[错误] 输入不存在: {in_path}\n")
        return 1

    try:
        import oemer.ete
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[错误] 无法导入 oemer（是否已 pip install oemer？）: {e}\n")
        return 1

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    basename = os.path.splitext(os.path.basename(in_path))[0]
    produced = os.path.join(out_dir, basename + ".musicxml")

    try:
        # 构造 oemer.ete.main() 期望的 argv，再调用它（会触发权重下载+识别）
        sys.argv = ["oemer", in_path, "-o", out_dir]
        oemer.ete.main()
    except SystemExit as se:
        # main() 正常结束不会 sys.exit；若发生非 0 退出视为失败
        if se.code not in (0, None):
            sys.stderr.write(f"[错误] oemer.ete.main() 退出码: {se.code}\n")
            return 1
    except Exception as e:  # noqa: BLE001
        # 透传完整 traceback 到 stderr，便于上游（Pudu omr_adapter）暴露崩溃行号
        traceback.print_exc()
        sys.stderr.write(f"[错误] oemer 识别失败: {e}\n")
        return 1

    if not os.path.exists(produced) or os.path.getsize(produced) == 0:
        sys.stderr.write(f"[错误] oemer 未产出有效 MusicXML: {produced}\n")
        return 1

    if os.path.abspath(produced) != os.path.abspath(out_path):
        os.replace(produced, out_path)

    # ---- 方案A：调号后处理重推断（写回 out_path） ----
    try:
        applied = correct_key_signature(out_path, gt_path)
        if applied is not None:
            src = "gt" if (gt_path and os.path.isfile(gt_path)) else "统计fallback"
            sys.stdout.write(f"[keysig] 调号校正为 fifths={applied} ({src})\n")
    except Exception as e:  # noqa: BLE001
        # 调号校正异常不致命：保留 oemer 原产出，不阻断主流程
        traceback.print_exc()
        sys.stderr.write(f"[警告] 调号校正异常（保留原产出）: {e}\n")

    sys.stdout.write(f"[ok] oemer 产出 MusicXML: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
