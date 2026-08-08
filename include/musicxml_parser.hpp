#ifndef PUDU_MUSICXML_PARSER_HPP
#define PUDU_MUSICXML_PARSER_HPP

// ----------------------------------------------------------------------
// 谱渡 Pudu · MusicXML(score-partwise) 解析器骨架
//
// 职责：从文件/字符串加载 -> 遍历关键节点 -> 填充 Score 内存模型。
// 当前只覆盖 MVP 标签集（见 musicxml_mvp_tags.md）；后续扩展按该清单增量添加。
//
// 用法：
//   pudu::Score score;
//   pudu::MusicXMLParser parser;
//   std::string err;
//   if (!parser.loadFromFile("data/sample.musicxml", score, err)) { /* 处理 err */ }
// ----------------------------------------------------------------------

#include "score_model.hpp"

#include <pugixml.hpp>
#include <string>

namespace pudu {

class MusicXMLParser {
public:
    // 从文件路径加载并解析；成功返回 true，错误信息写入 err
    bool loadFromFile(const std::string& path, Score& out, std::string& err);

    // 从 XML 字符串加载并解析（便于单元测试 / 内存样例）
    bool parseString(const std::string& xml, Score& out, std::string& err);

private:
    // 解析 document 树（供上面两者复用）
    bool parseDocument(const pugi::xml_document& doc, Score& out, std::string& err);

    // 解析所有 <credit>/<credit-words> 抬头行，填充 out.credits
    void parseCredits(const pugi::xml_node& root, Score& out);

    // 解析单个 <part> 节点（含其 <attributes> 与所有 <measure>）
    void parsePart(const pugi::xml_node& partNode, Score& out);

    // 解析 <measure>：填充首次出现的 <attributes> 与本小节 <note>
    void parseMeasure(const pugi::xml_node& measureNode, Part& part);

    // 解析单个 <note>：填充 Note（音高 / 休止 / 时值 / 附点 / 延音 / onset / voice
    //   / chordPitches / isGrace）。divisions 用于时间游标推进。
    void parseNote(const pugi::xml_node& noteNode, Measure& measure, int divisions);

    // MVP：当前声部是否已读取过 <attributes>（每部谱独立，仅读取一次）
    bool attributesSeen_ = false;

    // P1-1：当前生效的"拍号"（随每个含 <time> 的 <measure> 更新，向后沿用上一个值）。
    //   与 part.attributes.beats（仅取首拍号作全局默认）解耦，从而支持曲中变拍号，
    //   供后处理引擎做"逐小节"节拍对账。
    int currentBeats_ = 0;
    int currentBeatType_ = 0;

    // 全局默认拍号是否已由"首 <time> 块"写入 part.attributes。
    //   守卫不能依赖数值哨兵：ScoreAttributes::beats 默认 4，旧 `== 0` 判断永不
    //   触发，导致非 4/4 谱（2/4、3/4、6/4…）的全局拍号恒错，BeatReconcile 的
    //   逐小节目标全部落回 4/4。P1-1 返工：改为显式标志，首块写入后置位。
    bool timeDefaultSeen_ = false;

    // 阶段 2 前置：本声部内的时间游标（单位 = quarterLength / 四分音符），跨小节连续推进；
    //   每遇非和弦 <note> 前进 duration/divisions，遇 <backup>/<forward> 按同换算回退/前进。
    //   每个 <note> 的 onset 即取当前游标值。每部谱开始时重置为 0。
    double qcursor_ = 0.0;
};

} // namespace pudu

#endif // PUDU_MUSICXML_PARSER_HPP
