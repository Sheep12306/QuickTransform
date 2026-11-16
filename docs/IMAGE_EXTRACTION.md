# Word 图片提取与 ShowDoc 占位符

本模块直接解析 DOCX（ZIP + OOXML），按正文实际出现顺序提取图片，并在 Markdown 原位置写入唯一占位符。模块不执行任何上传，ShowDoc URL 由人工处理。

## 网页版：只提取并展示图片

启动本地服务后打开：

```text
http://127.0.0.1:8000/word2image.html
```

或从首页点击「Word 图片提取」。

这个页面提取 DOCX 中的图片并按正文顺序罗列，不生成 Markdown。支持：

- 兼容性预检分类：`supported` / `converted` / `oversized` / `conversion_failed` / `unsupported`
- 按格式筛选（PNG、JPG、GIF、EMF 等）
- 勾选单张 / 多张图片
- 单张复制（写入上传副本）
- 全选后点击「复制选中」批量复制（多图剪贴板）
- 选中后「打包下载」为 ZIP（打包上传副本）
- 单张「下载原图」始终保存 DOCX 内原始字节和原扩展名
- 转换/超限图片可单独「下载上传副本」
- 查看 `manifest.json`

普通 PNG/JPEG 的上传副本与原始字节完全一致；EMF/WMF/TIFF 会生成 PNG 上传副本；大型 PNG/JPEG 会生成适合文档查看的预览上传副本。原始文件始终保留。

浏览器对多图剪贴板的支持不一致。勾选多张后点击「复制选中」会先尝试多图写入，再使用 HTML 多图模式；如果粘贴到 ShowDoc 后只出现一张，请使用每张图片上的「复制」按钮逐张粘贴。

## 命令行使用

命令行：

```powershell
.tools\python312\python.exe -m w2md extract-images samples\sample_prd.docx -o output
```

等价于：

```powershell
.tools\python312\python.exe -m w2md convert samples\sample_prd.docx -o output --assets placeholder
```

网页界面选择「图片 → 占位符」即可。

输出结构：

```
output/
  sample_prd.md
  assets/
    manifest.json
    original/
      sample_prd-image-000001.png
      sample_prd-image-000005.emf
    upload/
      sample_prd-image-000001.png
      sample_prd-image-000005.png
```

`assets/original/` 保存 DOCX 内原始字节；`assets/upload/` 保存用于 ShowDoc 上传的副本。

Markdown 中不再嵌入图片路径或 Base64，正常图片位置为：

```markdown
{{SHOWDOC_IMAGE_000001}}
```

无法自动处理的图片保留原序号，并使用特殊占位符：

```markdown
{{SHOWDOC_UNSUPPORTED_IMAGE_000018}}
{{SHOWDOC_OVERSIZED_IMAGE_000019}}
{{SHOWDOC_CONVERSION_FAILED_IMAGE_000020}}
{{SHOWDOC_EMBEDDED_000021}}
```

后续图片不会因为特殊图片而重新编号。同一媒体文件在文档中重复出现时，只会保存一份原图和一份上传副本，但每个出现位置仍然使用独立 `occurrence_id` 和占位符。

嵌入的 Word 文档、视频、HTML 和 OLE 对象不提取、不转换、不替换，只生成 `{{SHOWDOC_EMBEDDED_...}}` 占位符并提醒人工在 ShowDoc 上传原文件；其预览图标/视频封面不会被当作普通图片处理。网页工具栏可一键复制 manifest.json，或下载带原文档名的 `<文档名>.manifest.json`。

## 识别范围

- DrawingML：`a:blip@r:embed`
- VML：`v:imagedata@r:id`
- 嵌入对象：`w:object` / `o:OLEObject`、`a:videoFile`、`w:altChunk`、`w:control`
- 正文段落、表格单元格、列表段落、同一段落多张图片
- 同一图片重复出现

图片按 `word/document.xml` 的元素出现顺序编号，不按 `image1`、`image2` 文件名排序。

## 字节保真与上传副本

- 原始图片：直接从 ZIP 读取 `word/media/*` 原始字节写入 `assets/original/`，不经过图片库解码/重新编码，保持原扩展名。
- 写入后重新读取并计算 SHA-256，与 DOCX 内原始字节比对，结果写入 `sha256_verified`。
- 普通 PNG/JPEG/GIF/BMP/WebP：把原始字节原样复制到 `assets/upload/`，`upload_sha256 == source_sha256`。
- EMF/WMF/TIFF：保留原始文件，使用 Pillow / PyMuPDF 渲染为高分辨率 PNG 上传副本，`upload_sha256` 单独计算。
- 大型 PNG/JPEG：超过阈值时生成文档查看用的预览上传副本（优先 PNG，必要时 JPEG），分类为 `oversized`，保留特殊占位符。
- 转换失败或浏览器无法处理的格式：保留原始文件，分类为 `conversion_failed` / `unsupported`，保留特殊占位符。

## 兼容性分类

| 分类 | 占位符 | 上传副本 | 说明 |
| --- | --- | --- | --- |
| `supported` | 普通 `{{SHOWDOC_IMAGE_...}}` | 原字节复制 | 可直接上传 |
| `converted` | 普通 `{{SHOWDOC_IMAGE_...}}` | PNG | EMF/WMF/TIFF 已转换 |
| `oversized` | `{{SHOWDOC_OVERSIZED_IMAGE_...}}` | 预览 PNG/JPEG | 超过大小/像素阈值；副本供人工使用，不自动替换 |
| `conversion_failed` | `{{SHOWDOC_CONVERSION_FAILED_IMAGE_...}}` | 无 | 转换失败 |
| `unsupported` | `{{SHOWDOC_UNSUPPORTED_IMAGE_...}}` | 无 | 不支持的格式 |
| `embedded` | `{{SHOWDOC_EMBEDDED_...}}` | 无 | 嵌入的 Word/视频/HTML/OLE 对象，仅提醒人工上传 |

默认阈值：

- 上传副本大小上限：5 MB（`--max-upload-mb 5`）
- 原始像素长边上限：4000（`--max-image-dimension 4000`）
- 超限预览长边：2000（`--preview-max-dimension 2000`）

`--no-image-previews` 会禁用转换和预览生成，EMF/WMF/TIFF 以及超限图片会进入特殊占位符分类。

## manifest 示例

```json
{
  "schema_version": 1,
  "document_id": "doc-cd8aaf91f70df7f7fefb76a26ce21aff",
  "source_file": "sample_prd.docx",
  "markdown_file": "sample_prd.md",
  "created_at": "2026-11-16T10:00:00+08:00",
  "compatibility_thresholds": {
    "max_upload_bytes": 5242880,
    "max_image_dimension": 4000,
    "preview_max_dimension": 2000
  },
  "placeholder_prefixes": {
    "normal": "{{SHOWDOC_IMAGE_",
    "unsupported": "{{SHOWDOC_UNSUPPORTED_IMAGE_",
    "oversized": "{{SHOWDOC_OVERSIZED_IMAGE_",
    "conversion_failed": "{{SHOWDOC_CONVERSION_FAILED_IMAGE_"
  },
  "summary": {
    "occurrences": 2,
    "unique_media": 1,
    "duplicates": 1,
    "supported": 1,
    "converted": 0,
    "oversized": 0,
    "conversion_failed": 0,
    "unsupported": 0,
    "special": 0,
    "failed": 0,
    "unreferenced_media": 0
  },
  "images": [
    {
      "sequence": 1,
      "occurrence_id": "IMG_OCC_000001",
      "placeholder": "{{SHOWDOC_IMAGE_000001}}",
      "source_file": "assets/original/sample_prd-image-000001.png",
      "source_format": "png",
      "source_sha256": "e1fdb2948a03bd72fc9966a6f03b657f5c7eac3a299ca7edbb3d675fa9be1df8",
      "upload_file": "assets/upload/sample_prd-image-000001.png",
      "upload_format": "png",
      "upload_sha256": "e1fdb2948a03bd72fc9966a6f03b657f5c7eac3a299ca7edbb3d675fa9be1df8",
      "size": 105654,
      "mime_type": "image/png",
      "compatibility": "supported",
      "requires_conversion": false,
      "alt_text": "示例图片",
      "section": "需求背景",
      "context_before": "示例图片前的正文",
      "context_after": "示例图片后的正文"
    },
    {
      "sequence": 17,
      "occurrence_id": "IMG_OCC_000017",
      "placeholder": "{{SHOWDOC_IMAGE_000017}}",
      "source_file": "assets/original/sample_prd-image-000017.emf",
      "source_format": "emf",
      "source_sha256": "原始 EMF SHA-256",
      "upload_file": "assets/upload/sample_prd-image-000017.png",
      "upload_format": "png",
      "upload_sha256": "转换后 PNG SHA-256",
      "size": 417899,
      "mime_type": "image/png",
      "compatibility": "converted",
      "requires_conversion": true,
      "section": "3.2 采购订单流程",
      "context_before": "提交订单后进入审批",
      "context_after": "审批通过后生成入库单"
    }
  ],
  "unreferenced_media": [],
  "errors": [],
  "notes": [
    "未执行任何上传；showdoc_url 与 upload_status 由人工处理。"
  ]
}
```

### 字段说明

- `document_id`：由 `document.xml` 规范化和所有 `word/media/*` 原始字节哈希计算，重新转换同一文档时保持不变；文档内容或图片变化时会变化。导入 `upload_result.json` 时用于防止拿错文档。
- `sequence`：图片在正文中的出现序号，从 1 开始；特殊图片也保留原序号。
- `occurrence_id`：每个正文位置的唯一 ID，格式 `IMG_OCC_%06d`。同一图片重复出现时，`sequence`、`occurrence_id`、`placeholder` 不同，`source_file`、`upload_file`、`source_sha256`、`upload_sha256` 相同。
- `source_file` / `upload_file`：原始文件与上传副本的路径，相对于输出目录；路径使用 `/`。
- `source_sha256`：DOCX 内原始图片字节的 SHA-256。
- `upload_sha256`：上传副本字节的 SHA-256。普通图片与 `source_sha256` 相同；转换图片必须使用该值匹配上传记录。
- `compatibility`：`supported` / `converted` / `oversized` / `conversion_failed` / `unsupported` / `embedded`。
- `requires_conversion`：上传副本是否需要转换/重新生成。
- `section`：向前查找最近的大纲级别/标题样式段落，作为所在章节。
- `context_before` / `context_after`：图片同一段落中图前、图后的文字；为空时取相邻段落。仅用于缺失清单定位，已截断。
- 旧字段 `order`、`local_path`、`sha256`、`document`、`generated_at` 继续保留，方便旧调用方兼容。

## alt 文本来源

按以下顺序取第一个可用值：

1. `wp:docPr@descr`
2. `wp:docPr@title`
3. `pic:cNvPr@descr`
4. `pic:cNvPr@title`
5. VML `v:shape@alt` / `@title`
6. 附近图注（紧接着的段落，匹配「图 1」「Figure 1」等）
7. 兜底 `图片N`

`alt_source` 字段记录实际来源，便于核对。

## 兼容格式与依赖

EMF、WMF、TIFF 会保留原始文件，并尝试使用 Pillow / PyMuPDF 生成高分辨率 PNG 上传副本。若两个库都无法渲染（例如缺少系统级 EMF 支持），该图片会分类为 `conversion_failed`，保留 `{{SHOWDOC_CONVERSION_FAILED_IMAGE_...}}` 特殊占位符，不会静默丢失或重排后续图片。

大型 PNG/JPEG 使用 Pillow / PyMuPDF 生成预览上传副本。若无法压缩到阈值以内，会分类为 `oversized`，保留特殊占位符。

## 异常报告

以下情况都会写入 manifest 的 `errors` 或 `unreferenced_media`：

- relationship 不存在
- 外部链接图片
- media 文件缺失
- 读取/写入失败
- SHA-256 校验失败
- 上传副本转换失败
- 图片格式不支持
- 图片超过上传阈值
- `word/media/` 中未被正文引用的文件
- 正文本身已包含占位符样式文本

如果图片位于文本框等当前 Markdown 解析器未支持的结构中，图片仍会被提取，但占位符可能没有出现在 Markdown 里；报告中会出现 `image_placeholder_unplaced`。

## 已知限制

- 不执行 ShowDoc 上传或 URL 回填（按约定由人工处理）。
- 浏览器对多图剪贴板支持不一致；工具会依次尝试 Clipboard API 和 HTML 多图模式，仍失败时退化为复制第一张，并提示逐张复制。
- EMF/WMF/TIFF 的转换效果取决于 Pillow / PyMuPDF 对格式的支持；转换失败会进入特殊占位符，不会提交到自动替换流程。
- `oversized` 会生成预览上传副本，但按约定保留特殊占位符，不自动替换；预览副本可在图片工具中复制/下载后人工处理。
- 页眉、页脚中的图片不属于正文，会出现在 `unreferenced_media` 中。
- 文本框、嵌套表格等结构尚未进入 Markdown 渲染时，对应占位符可能未落位，但会报告。
- 多个 DOCX 输出到同一个 `output` 目录时，`assets/manifest.json` 会被后一次运行覆盖；批量处理建议每个文档使用独立输出目录。
- 普通图片会在 `assets/original/` 和 `assets/upload/` 各保存一份，磁盘占用约为原图的两倍（重复出现仍只保存一份）。
