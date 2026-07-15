#ifndef PUDU_JIANPU_CONVERTER_HPP
#define PUDU_JIANPU_CONVERTER_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · 阶段 2 简谱转换器（Score -> JianpuDoc）
//
// 依据 omr-tool-research/jianpu_output_spec.md 实现 staffToJianpu 及核心纯函数。
// 设计：转换对 Score 只读、不回改；结果是一份 L0 语义投影，
//       供 L1(纯文本) / L2(二维) 渲染器各自投影，阶段 3 反转换直接消费 L0。
//
// 纯函数（midiToJianpu / typeToDuration / fifthsToTonic*）独立可单测，
// 覆盖规范 §5 的边界用例；staffToJianpu 主流程见规范 §4 伪代码。
// ----------------------------------------------------------------------

#include "jianpu_model.hpp"
#include "score_model.hpp"

#include <string>

namespace pudu {

// 五度圈步数 -> 主音音级(0-11)。
//   tonicPc = (fifths * 7) mod 12（取正模）。
//   C=0 G=7 D=2 A=9 E=4 B=11 F#=6 Bb=10 Eb=3 Ab=8 ...（规范 §2.1）
inline int fifthsToTonicPc(int fifths) {
    int pc = (fifths * 7) % 12;
    if (pc < 0) pc += 12;
    return pc;
}

// 调号 -> 调名字母（MVP 覆盖 ±7 个升降号）。
//   0=C 1=G 2=D 3=A 4=E 5=B 6=F#  -1=F -2=Bb -3=Eb -4=Ab -5=Db -6=Gb
// 小调默认首调相对法：1 落关系大调主音，故直接复用同名大调字母
//   （关系大调与本调共享同一调号，fifths 相同）。可选 "6=X" 标法后置。
std::string fifthsToTonicName(int fifths, const std::string& mode);

// 绝对音高(Pitch) + 主音音级 -> (音级, 临时记号, 八度点)。
//   命中大调音阶: 纯音级, accidental=None。
//   调外音: 按源 alter 择优 —— alter<0 取 (semi+1) 音级 + Flat；
//           否则取 (semi-1) 音级 + Sharp。
//   （规范 §2.1；等音异名边界如 G#/Ab 的正确记法后置，详见可行性分析）
void midiToJianpu(const Pitch& pitch, int tonicPc,
                  int& outDegree, Accidental& outAccidental, int& outOctaveDots);

// 仅取音级（和弦其余音 / 校验用）。
inline int midiToDegree(const Pitch& pitch, int tonicPc) {
    int d = 0; Accidental a = Accidental::None; int o = 0;
    midiToJianpu(pitch, tonicPc, d, a, o);
    return d;
}

// 时值类型(type) -> (减时线数, 增时线数)。未识别按四分(0,0)处理（规范 §2.3）。
void typeToDuration(const std::string& type, int& outUnderlines, int& outAugmentDashes);

// 主转换：Score -> JianpuDoc。
//   按 part / voice / measure 组织；同小节音符按 onset 升序；
//   多声部 -> 多行(JianpuLine)。全局属性(调号/拍号)取首声部(MVP 单声部假设)。
JianpuDoc staffToJianpu(const Score& score);

// L1 纯文本渲染（ASCII-first），用于命令行核对 / 单元测试，非生产渲染器。
//   抬头: 标题 / "1=X 4/4 (mode)"；每行 "voiceN: 音符 | 音符 ||"。
//   记号: 升降八度 ' / , ；减时线 _ ；增时线 " -"；附点 . ；临时记号 #/b/n；
//        和弦 [d d ...]；装饰音 g 前缀；连音线 ~ 后缀（L2 用 SVG 弧）。
std::string jianpuToL1(const JianpuDoc& doc);

// L2 HTML/Unicode 二维渲染（规范 §3.2）：把 JianpuDoc 投影为真正的二维简谱。
//   返回自包含、可直接浏览器打开的 .html 字符串（含最小内联 CSS）。
//   核心要素：数字 span.jp-num；八度点上下定位(·)；减时线横向连写(同值连续音
//     成 beam 组，单条/多条横线贯穿)；增时线 —；附点 ·；和弦纵向 flex 列；
//     连音弧内联 SVG。仅投影 L0，不回改 Score。
std::string jianpuToL2(const JianpuDoc& doc);

// L3 结构化输出（JSON 字符串）：把 JianpuDoc 投影为无损、可被脚本解析的 JSON，
//   供 verify_jianpu_groundtruth.py 等外部校验器逐音比对。仅投影 L0，不回改 Score。
//   结构见 jianpu_model.hpp；顶层含 title/tonicLabel/mode/fifths/beats/beatType/lines，
//   每个音符含 degree/octaveDots/accidental/underlines/augmentDashes/dots/
//        isRest/isGrace/tieToNext/tuplet/chordDegrees。
std::string jianpuToJson(const JianpuDoc& doc);

} // namespace pudu

#endif // PUDU_JIANPU_CONVERTER_HPP
