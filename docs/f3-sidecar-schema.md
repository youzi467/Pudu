# F3 几何 sidecar Schema 契约

> 配套：`tools/geometric_pitch.py`、`tools/omr_oemer.py`（`_dump_geometry_sidecar`）、
> `docs/system_design.md` §3。
> 本文件供工程师 / QA 校验 `<basename>.geometry.json` 是否符合契约。

## 1. 文件名与量纲

- **文件名**：与产出 `.musicxml` **同目录、同名** `.geometry.json`
  （例：`concerto-in-a-minor-a-vivaldi_p1.musicxml`
   → `concerto-in-a-minor-a-vivaldi_p1.geometry.json`）。
- **坐标量纲** `coordinate_space = "pixel_model"`：oemer 将原始图 resize 到预测分辨率
  （`staff_pred.shape`）后的坐标系。音符 `bbox` / 谱线 `lines[].y_center` / `center` /
  `ink_centroid` 均在此空间，相对几何自洽——这正是 F3 重算所需的全部信息。

## 2. JSON Schema（draft-07）

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://pudu.local/f3/geometry.schema.json",
  "title": "Oemer F3 Geometry Sidecar",
  "type": "object",
  "required": ["schema_version", "source_image", "musicxml", "coordinate_space",
               "note_order", "staves", "clefs", "notes"],
  "properties": {
    "schema_version": {"type": "integer", "const": 1},
    "generator": {"type": "string"},
    "source_image": {"type": "string"},
    "musicxml": {"type": "string"},
    "coordinate_space": {"type": "string", "enum": ["pixel_model"]},
    "note_order": {"type": "string", "enum": ["oemer_emission"],
                   "description": "notes[] 顺序 == MusicXML <note> 文档序 1:1"},
    "unit_size_px": {"type": "number", "minimum": 0,
                     "description": "oemer 全局 unit_size（参考）"},
    "image_width_px": {"type": "number"},
    "image_height_px": {"type": "number"},
    "staves": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["staff_id", "track", "unit_size", "lines"],
        "properties": {
          "staff_id": {"type": "integer"},
          "track": {"type": "integer", "description": "0-based，对应 <staff>=track+1 / clef.track"},
          "group": {"type": ["integer", "null"]},
          "unit_size": {"type": "number", "exclusiveMinimum": 0,
                        "description": "谱线间距（px），half_step = unit_size/2"},
          "y_center": {"type": "number"},
          "lines": {
            "type": "array",
            "minItems": 5, "maxItems": 5,
            "items": {
              "type": "object",
              "required": ["y_center"],
              "properties": {
                "y_center": {"type": "number"},
                "thickness": {"type": "number"}
              }
            }
          }
        }
      }
    },
    "clefs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["track", "type"],
        "properties": {
          "track": {"type": "integer"},
          "type": {"type": "string", "enum": ["G", "F", "C", "percussion"]},
          "sign": {"type": "string"},
          "line": {"type": ["integer", "null"]},
          "x_center": {"type": "number"},
          "y_center": {"type": ["number", "null"]}
        }
      }
    },
    "notes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "track", "bbox", "center", "ink_centroid", "staff_line_pos"],
        "properties": {
          "id": {"type": "integer", "description": "oemer note id == 发射序索引"},
          "track": {"type": "integer"},
          "group": {"type": ["integer", "null"]},
          "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4,
                   "description": "[x1, y1, x2, y2] 符头 bbox"},
          "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                     "description": "[cx, cy] bbox 中心"},
          "ink_centroid": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                           "description": "[cx, cy] 墨迹像素质心（重算主输入，比 bbox 中心更稳）"},
          "staff_line_pos": {"type": "integer",
                             "description": "oemer 原猜 diatonic pos（pos=0=D4 @G 谱号），仅供 A/B"},
          "sfn": {"type": ["string", "null"], "enum": ["sharp", "flat", "natural", null]}
        }
      }
    }
  }
}
```

## 3. concerto p1 示例（单谱表 G 谱号，节选 2 音）

```json
{
  "schema_version": 1,
  "generator": "pudu-f3-sidecar",
  "source_image": "concerto-in-a-minor-a-vivaldi_p1.jpg",
  "musicxml": "concerto-in-a-minor-a-vivaldi_p1.musicxml",
  "coordinate_space": "pixel_model",
  "note_order": "oemer_emission",
  "unit_size_px": 11.34,
  "image_width_px": 2480,
  "image_height_px": 3508,
  "staves": [
    {
      "staff_id": 0,
      "track": 0,
      "group": 0,
      "unit_size": 11.20,
      "y_center": 1234.5,
      "lines": [
        {"y_center": 1256.0, "thickness": 2.1},
        {"y_center": 1245.0, "thickness": 2.0},
        {"y_center": 1234.0, "thickness": 2.2},
        {"y_center": 1223.0, "thickness": 2.0},
        {"y_center": 1212.0, "thickness": 2.1}
      ]
    }
  ],
  "clefs": [
    {"track": 0, "type": "G", "sign": "G", "line": null, "x_center": 82.4, "y_center": 1234.0}
  ],
  "notes": [
    {"id": 0, "track": 0, "group": 0,
     "bbox": [140.0, 1196.5, 158.2, 1214.7], "center": [149.1, 1205.6],
     "ink_centroid": [149.3, 1205.1], "staff_line_pos": 9, "sfn": null},
    {"id": 1, "track": 0, "group": 0,
     "bbox": [210.5, 1230.0, 228.7, 1248.2], "center": [219.6, 1239.1],
     "ink_centroid": [219.4, 1238.8], "staff_line_pos": 4, "sfn": null}
  ]
}
```

## 4. 字段契约（与 MusicXML 音符关联）

- **主键（稳健）**：`notes[]` 顺序 = `EMISSION_ORDER` = MusicXML `<note>`（非休止）**文档序** 1:1。
  Pudu 侧按文档序遍历 `<part>/<measure>/<note>`，跳过 `<rest>`，第 i 个音 ↔ `sidecar.notes[i]`。
- **辅键（退化/B 计划）**：若发射序捕获失败，`notes[]` 退化为按 `(track, x_center)` 排序对齐
  （sidecar 已含 `track` 与 `ink_centroid[0]`=x；MusicXML 音符按同 track 左→右排序后位置 1:1）。
- `note.track` ↔ `clefs[].track` ↔ MusicXML `<staff>`（=track+1）三方一致，用于取谱号类型与选 anchor。
- `clef.type` 由 oemer `Clef.label`（`G_CLEF`/`F_CLEF`）映射为 `"G"`/`"F"`；**oemer 的 `Clef`
  不暴露 `line`/`y_center`**，故 sidecar 中 `clef.line` 恒为 `null`、`clef.y_center` 由 bbox 推导
  （仅供参考，F3 几何不依赖它们）。
- `note.ink_centroid` 由 oemer `NoteHead.points`（存为 `(y, x)` 元组）求墨迹质心 `(cx, cy)`；
  极少数退化符头无 points 时回落为 bbox 中心。
- `note.staff_line_pos` 为 oemer 原猜 diatonic pos，F3 仅用于「cy 可疑」退化检测
  （|几何 pos − 原猜| > 16 半音级时跳过），并对 A/B 对比开放。

## 5. 生产者 / 消费者

- **生产者**：`tools/omr_oemer.py` 的 `_dump_geometry_sidecar`（运行时 monkeypatch
  `oemer.ete.extract` + `oemer.build_system.AddNote.perform`，**零改 site-packages**）。
  默认随 oemer 产出；`--no-f3-sidecar` 可抑制。
- **消费者**：`tools/geometric_pitch.py` 的 `recompute_pitch_from_geometry`
  （`SidecarDoc.from_dict` 解析），按发射序 1:1 覆盖 `<step>/<octave>`。
- **校验**：QA 可用任意 draft-07 校验器对 §2 schema 校验；`schema_version` 当前固定为 `1`。
