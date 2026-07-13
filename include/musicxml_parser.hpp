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

    // 解析单个 <part> 节点（含其 <attributes> 与所有 <measure>）
    void parsePart(const pugi::xml_node& partNode, Score& out);

    // 解析 <measure>：填充首次出现的 <attributes> 与本小节 <note>
    void parseMeasure(const pugi::xml_node& measureNode, Part& part);

    // 解析单个 <note>：填充 Note（音高 / 休止 / 时值 / 附点 / 延音）
    void parseNote(const pugi::xml_node& noteNode, Measure& measure);

    // MVP：当前声部是否已读取过 <attributes>（每部谱独立，仅读取一次）
    bool attributesSeen_ = false;
};

} // namespace pudu

#endif // PUDU_MUSICXML_PARSER_HPP
