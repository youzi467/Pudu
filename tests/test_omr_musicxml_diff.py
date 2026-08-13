# -*- coding: utf-8 -*-
"""MusicXML 层差异检测（tools/omr_musicxml_diff.py）单测。

覆盖：
  * 解析层：divisions 继承、grace 无 duration、tie start/stop、chord 独立事件、
    命名空间剥除、doc_meta / midi 推导。
  * 比对层：identical 零差异；step/duration/rest/grace/chord/tie 失配类别。
  * 对齐层：同序同长零 leftover；pred 多音 → c_left 进 event_count；节奏错但音高对
    → 仍配对（NW 音高锚定）。
  * diff_files 端到端：同内容 note_pass=100；fifths 差异 → key；pred 多音 → event_count。
  * 真实语料冒烟（@skipUnless build/_av_eval13 存在）：canon 对齐、bach 小节不齐容错、
    doc_meta 无 key diff。

纯 stdlib（xml.etree / unittest），不依赖 oemer / music21 / Pudu.exe。
"""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import omr_musicxml_diff as mxd  # noqa: E402

AV13 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "build", "_av_eval13")


# ----------------------------------------------------------------------
# 合成 MusicXML 工具
# ----------------------------------------------------------------------

def _note(step=None, octave=4, alter=0, dur="8", typ="quarter", div=8,
          rest=False, grace=False, chord=False, tie=None):
    """构造一个 <note> 字符串。tie ∈ {None, 'start', 'stop'}。"""
    parts = ["<note>"]
    if grace:
        parts.append("<grace/>")
    if chord:
        parts.append("<chord/>")
    if rest:
        parts.append("<rest/>")
    else:
        parts.append(f"<pitch><step>{step}</step>"
                     + (f"<alter>{alter}</alter>" if alter else "")
                     + f"<octave>{octave}</octave></pitch>")
    parts.append(f"<duration>{dur}</duration>")
    parts.append(f"<type>{typ}</type>")
    if tie:
        parts.append(f'<tie type="{tie}"/>')
    parts.append("</note>")
    return "".join(parts)


def _measure(num, notes, div=8):
    """构造一个 <measure>，含 attributes/divisions。"""
    attrs = (f"<attributes><divisions>{div}</divisions>"
             f"<key><fifths>2</fifths></key>"
             f"<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
             if num == 1 else "")
    return f"<measure number=\"{num}\">{attrs}{''.join(notes)}</measure>"


def _score(*measures, version="4.0.3", ns=False):
    """构造完整 score-partwise 字符串。ns=True 时带默认命名空间。"""
    root = ("<score-partwise xmlns=\"http://www.musicxml.org/ns/3.0\" "
            f"version=\"{version}\">" if ns
            else f"<score-partwise version=\"{version}\">")
    return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            f"{root}"
            f"<part-list><score-part id=\"P1\"><part-name>P1</part-name>"
            f"</score-part></part-list>"
            f"<part id=\"P1\">{''.join(measures)}</part></score-partwise>")


def _write_score(path, notes, *, measures=None, div=8, ns=False, version="4.0.3"):
    """写一个单 part 单小节（或指定 measures）的 MusicXML 到临时文件。"""
    if measures is None:
        measures = [_measure(1, notes, div)]
    root_tag = ("<score-partwise xmlns=\"http://www.musicxml.org/ns/3.0\" "
                f"version=\"{version}\">" if ns
                else f"<score-partwise version=\"{version}\">")
    xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
           f"{root_tag}"
           f"<part-list><score-part id=\"P1\"><part-name>P1</part-name>"
           f"</score-part></part-list>"
           f"<part id=\"P1\">{''.join(measures)}</part></score-partwise>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


# ----------------------------------------------------------------------
# 解析层
# ----------------------------------------------------------------------

class TestParse(unittest.TestCase):

    def test_divisions_inherit(self):
        # m1 有 attributes/divisions=8，m2 无 → m2 事件 qlen 用 8
        xml = _score(
            _measure(1, [_note("C", dur="8", typ="quarter")], div=8),
            "<measure number=\"2\"><note><pitch><step>D</step>"
            "<octave>4</octave></pitch><duration>4</duration>"
            "<type>eighth</type></note></measure>")
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            _meta, parts = mxd.parse_musicxml(p)
            evs = parts["P1"]
            self.assertEqual(len(evs), 2)
            self.assertEqual(evs[1]["qlen"], 4 / 8.0)   # m2 继承 divisions=8
            self.assertEqual(evs[1]["duration"], 4)
        finally:
            os.unlink(p)

    def test_grace_no_duration(self):
        xml = _score(_measure(1, [_note("C", dur="0", typ="eighth", grace=True)]))
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            _meta, parts = mxd.parse_musicxml(p)
            ev = parts["P1"][0]
            self.assertTrue(ev["isGrace"])
            self.assertEqual(ev["duration"], 0)
            self.assertEqual(ev["qlen"], 0.0)
            self.assertEqual(ev["type"], "eighth")
        finally:
            os.unlink(p)

    def test_tie_start_stop(self):
        xml = _score(_measure(1, [
            _note("C", dur="8", typ="quarter", tie="start"),
            _note("D", dur="8", typ="quarter", tie="stop"),
        ]))
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            _meta, parts = mxd.parse_musicxml(p)
            evs = parts["P1"]
            self.assertTrue(evs[0]["tieToNext"])
            self.assertFalse(evs[0]["tieFromPrev"])
            self.assertTrue(evs[1]["tieFromPrev"])
            self.assertFalse(evs[1]["tieToNext"])
        finally:
            os.unlink(p)

    def test_chord_extra_note(self):
        xml = _score(_measure(1, [
            _note("C", dur="8", typ="quarter"),
            _note("E", dur="8", typ="quarter", chord=True),
        ]))
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            _meta, parts = mxd.parse_musicxml(p)
            evs = parts["P1"]
            self.assertFalse(evs[0]["isChord"])
            self.assertTrue(evs[1]["isChord"])
            self.assertEqual(evs[1]["midi"], mxd._midi("E", 0, 4))  # E4=64
            self.assertEqual(evs[1]["duration"], 8)
        finally:
            os.unlink(p)

    def test_namespace_stripped(self):
        xml = _score(_measure(1, [_note("C", dur="8", typ="quarter")]), ns=True)
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            _meta, parts = mxd.parse_musicxml(p)
            self.assertEqual(len(parts["P1"]), 1)
            self.assertEqual(parts["P1"][0]["step"], "C")
        finally:
            os.unlink(p)

    def test_doc_meta(self):
        xml = _score(_measure(1, [_note("C")]))
        with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
            f.write(xml)
            p = f.name
        try:
            meta, _parts = mxd.parse_musicxml(p)
            self.assertEqual(meta["fifths"], "2")
            self.assertEqual(meta["beats"], "4")
            self.assertEqual(meta["beatType"], "4")
        finally:
            os.unlink(p)

    def test_midi(self):
        self.assertEqual(mxd._midi("C", 0, 4), 60)
        self.assertEqual(mxd._midi("A", 1, 4), 70)   # A#4
        self.assertEqual(mxd._midi("", 0, 0), 0)     # rest


# ----------------------------------------------------------------------
# 比对层
# ----------------------------------------------------------------------

def _ev(step="C", octave=4, alter=0, dur="8", typ="quarter", div=8,
        rest=False, grace=False, chord=False, tie=None):
    """构造事件 dict（经 _parse_note 路径，保证字段齐全）。"""
    xml = _score(_measure(1, [_note(step, octave, alter, dur, typ, div,
                                    rest, grace, chord, tie)]))
    with tempfile.NamedTemporaryFile("w", suffix=".musicxml", delete=False) as f:
        f.write(xml)
        p = f.name
    try:
        _meta, parts = mxd.parse_musicxml(p)
        return parts["P1"][0]
    finally:
        os.unlink(p)


class TestCompare(unittest.TestCase):

    def test_identical_zero_diff(self):
        a = _ev("C", dur="8", typ="quarter")
        b = _ev("C", dur="8", typ="quarter")
        diffs, n = mxd.compare_musicxml_event(a, b)
        self.assertEqual(diffs, [])
        self.assertEqual(n, 9)   # step/alter/octave/midi + isChord + isGrace + tie x2 + rhythm

    def test_pitch_wrong(self):
        a = _ev("C", dur="8", typ="quarter")
        b = _ev("D", dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "pitch" for _, _, _, cat in diffs))
        self.assertFalse(any(cat == "rhythm" for _, _, _, cat in diffs))

    def test_rhythm_wrong(self):
        a = _ev("C", dur="4", typ="half")
        b = _ev("C", dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "rhythm" for _, _, _, cat in diffs))
        self.assertFalse(any(cat == "pitch" for _, _, _, cat in diffs))

    def test_rest_mismatch(self):
        a = _ev("C", dur="8", typ="quarter")
        b = _ev(rest=True, dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "rest" for _, _, _, cat in diffs))

    def test_grace_mismatch(self):
        a = _ev("C", dur="8", typ="quarter", grace=True)
        b = _ev("C", dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "grace" for _, _, _, cat in diffs))

    def test_chord_mismatch(self):
        a = _ev("C", dur="8", typ="quarter", chord=True)
        b = _ev("C", dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "chord" for _, _, _, cat in diffs))

    def test_tie_mismatch(self):
        a = _ev("C", dur="8", typ="quarter", tie="start")
        b = _ev("C", dur="8", typ="quarter")
        diffs, _n = mxd.compare_musicxml_event(a, b)
        self.assertTrue(any(cat == "tie" for _, _, _, cat in diffs))


# ----------------------------------------------------------------------
# 对齐层
# ----------------------------------------------------------------------

class TestAlign(unittest.TestCase):

    def test_identical_alignment(self):
        evs = [_ev("C"), _ev("D"), _ev("E")]
        pairs, c_left, g_left = mxd._align_per_part(evs, evs)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(c_left, [])
        self.assertEqual(g_left, [])

    def test_tolerates_insertion(self):
        gt = [_ev("C"), _ev("D"), _ev("E")]
        pred = [_ev("C"), _ev("F"), _ev("D"), _ev("E")]   # pred 多一音 F
        pairs, c_left, g_left = mxd._align_per_part(pred, gt)
        self.assertEqual(len(pairs), 3)   # C-D-E 仍配对
        self.assertEqual(len(c_left), 1)  # 多出的 F 记为 only-in-pred
        self.assertEqual(g_left, [])

    def test_pitch_anchor(self):
        gt = [_ev("C", dur="8", typ="quarter"), _ev("D", dur="8", typ="quarter")]
        pred = [_ev("C", dur="4", typ="half"), _ev("D", dur="4", typ="half")]  # 节奏全错
        pairs, c_left, g_left = mxd._align_per_part(pred, gt)
        self.assertEqual(len(pairs), 2)   # 音高锚定 → 仍配对
        self.assertEqual(c_left, [])
        self.assertEqual(g_left, [])


# ----------------------------------------------------------------------
# diff_files 端到端
# ----------------------------------------------------------------------

class TestDiffFiles(unittest.TestCase):

    def _diff(self, gt_notes, pred_notes):
        with tempfile.TemporaryDirectory() as d:
            gt_p = os.path.join(d, "gt.musicxml")
            pr_p = os.path.join(d, "pred.musicxml")
            _write_score(gt_p, gt_notes)
            _write_score(pr_p, pred_notes)
            rep, ledger = mxd.diff_files(pr_p, gt_p)
            return rep, ledger

    def test_identical_docs_zero_diffs(self):
        rep, _ledger = self._diff(
            [_note("C"), _note("D")], [_note("C"), _note("D")])
        self.assertEqual(rep["notes_compared"], 2)
        self.assertEqual(rep["notes_correct"], 2)
        self.assertEqual(rep["field_failed"], 0)
        self.assertEqual(rep["note_pass"], 100.0)
        self.assertEqual(rep["field_pass"], 100.0)

    def test_doc_meta_diff(self):
        with tempfile.TemporaryDirectory() as d:
            gt_p = os.path.join(d, "gt.musicxml")
            pr_p = os.path.join(d, "pred.musicxml")
            _write_score(gt_p, [_note("C")])
            # pred 用 fifths=0（改 key）
            xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                   f"<score-partwise version=\"4.0.3\">"
                   f"<part-list><score-part id=\"P1\"><part-name>P1</part-name>"
                   f"</score-part></part-list><part id=\"P1\">"
                   f"<measure number=\"1\"><attributes><divisions>8</divisions>"
                   f"<key><fifths>0</fifths></key>"
                   f"<time><beats>4</beats><beat-type>4</beat-type></time>"
                   f"</attributes>{_note('C')}</measure></part></score-partwise>")
            with open(pr_p, "w", encoding="utf-8") as f:
                f.write(xml)
            rep, _ledger = mxd.diff_files(pr_p, gt_p)
        self.assertGreater(rep["category_counts"].get("key", 0), 0)
        self.assertGreater(rep["field_failed"], 0)

    def test_event_count_leftover(self):
        # pred 多一音 → event_count 单列、计入 field_failed、不进 note_pass 分母
        rep, _ledger = self._diff(
            [_note("C"), _note("D")], [_note("C"), _note("F"), _note("D")])
        self.assertEqual(rep["category_counts"].get("event_count", 0), 1)
        self.assertGreater(rep["field_failed"], 0)
        self.assertEqual(rep["notes_compared"], 2)   # 分母不含 leftover

    def test_mode_skipped(self):
        # pred 无 <mode>（Audiveris 只写 fifths）→ 文档级不因 mode 假阳
        with tempfile.TemporaryDirectory() as d:
            gt_p = os.path.join(d, "gt.musicxml")
            pr_p = os.path.join(d, "pred.musicxml")
            _write_score(gt_p, [_note("C")])
            # gt 有 mode=minor 但 pred 无 mode —— 两者 fifths 相同 → 不应有 key 假阳
            xml = (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                   f"<score-partwise version=\"4.0.3\">"
                   f"<part-list><score-part id=\"P1\"><part-name>P1</part-name>"
                   f"</score-part></part-list><part id=\"P1\">"
                   f"<measure number=\"1\"><attributes><divisions>8</divisions>"
                   f"<key><fifths>2</fifths></key>"
                   f"<time><beats>4</beats><beat-type>4</beat-type></time>"
                   f"</attributes>{_note('C')}</measure></part></score-partwise>")
            with open(pr_p, "w", encoding="utf-8") as f:
                f.write(xml)
            rep, _ledger = mxd.diff_files(pr_p, gt_p)
            self.assertEqual(rep["category_counts"].get("key", 0), 0)
            self.assertEqual(rep["category_counts"].get("mode", 0), 0)


# ----------------------------------------------------------------------
# 真实语料冒烟
# ----------------------------------------------------------------------

@unittest.skipUnless(os.path.isdir(AV13), "build/_av_eval13 不存在（build/ 被 gitignore）")
class TestRealCorpusSmoke(unittest.TestCase):

    def _pair(self, base):
        pred = os.path.join(AV13, base + ".pred.musicxml")
        gt = os.path.join(AV13, base + ".gt.musicxml")
        if not os.path.isfile(gt):
            gt = os.path.join(AV13, base + ".gt.musicxml")
        return pred, gt

    def test_canon_p1_aligns(self):
        pred, gt = self._pair("canon-in-d-violin-solo_p1")
        self.assertTrue(os.path.isfile(pred) and os.path.isfile(gt))
        rep, _ledger = mxd.diff_files(pred, gt)
        self.assertGreater(rep["notes_compared"], 200)
        self.assertGreater(rep["note_pass"], 90.0)

    def test_bach_p1_measure_mismatch_tolerated(self):
        # bach_p1 GT 20 小节 vs pred 18 → NW 容增删，event_count>0
        pred, gt = self._pair("bach-cello-suite-no-1-for-violin_p1")
        if not (os.path.isfile(pred) and os.path.isfile(gt)):
            self.skipTest("bach_p1 语料缺失")
        rep, _ledger = mxd.diff_files(pred, gt)
        self.assertGreater(rep["notes_compared"], 200)
        self.assertGreater(rep["category_counts"].get("event_count", 0), 0)

    def test_doc_meta_real_no_key_diff(self):
        pred, gt = self._pair("canon-in-d-violin-solo_p1")
        if not (os.path.isfile(pred) and os.path.isfile(gt)):
            self.skipTest("canon_p1 语料缺失")
        rep, _ledger = mxd.diff_files(pred, gt)
        self.assertEqual(rep["category_counts"].get("key", 0), 0)

    def test_saint_saens_tie(self):
        # the-swan tie 密集 → 干净跑过 tie start/stop 解析
        pred, gt = self._pair("the-swan-violin-c-saint-saens")
        if not (os.path.isfile(pred) and os.path.isfile(gt)):
            self.skipTest("the-swan 语料缺失")
        rep, _ledger = mxd.diff_files(pred, gt)
        self.assertGreater(rep["notes_compared"], 100)
        self.assertGreater(rep["category_counts"].get("tie", 0), 0)


if __name__ == "__main__":
    unittest.main()
