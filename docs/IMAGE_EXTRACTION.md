# Word 图片提取与 ShowDoc 占位符

本模块直接解析 DOCX（ZIP + OOXML），按正文实际出现顺序提取图片，并在 Markdown 原位置写入唯一占位符。模块不执行任何上传，ShowDoc URL 由人工处理。

## 网页版：只提取并展示图片

启动本地服务后打开：

```text
http://127.0.0.1:8000/word2image.html
```

或从首页点击「Word 图片提取」。

这个页面只做一件事：提取 DOCX 中的原图并按正文顺序罗列，不生成 Markdown。支持：

- 按格式筛选（PNG、JPG、GIF、EMF 等）
- 勾选单张 / 多张图片
- 单张复制（写入 PNG 剪贴板）
- 全选后点击「复制选中」批量复制（多图剪贴板）
- 选中后「打包下载」为 ZIP
- 单张下载原文件
- 查看 `manifest.json`

复制到剪贴板时，为保证浏览器兼容性会转换为 PNG；「下载」按钮保存的始终是 DOCX 内原始字节和原扩展名。

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
    sample_prd-image-000001.png
    manifest.json
```

Markdown 中不再嵌入图片路径或 Base64，图片位置为：

```markdown
{{SHOWDOC_IMAGE_000001}}
```

同一媒体文件在文档中重复出现时，只会复制一次，但每个出现位置仍然使用独立占位符。

## 识别范围

- DrawingML：`a:blip@r:embed`
- VML：`v:imagedata@r:id`
- 正文段落、表格单元格、列表段落、同一段落多张图片
- 同一图片重复出现

图片按 `word/document.xml` 的元素出现顺序编号，不按 `image1`、`image2` 文件名排序。

## 字节保真

- 直接从 ZIP 读取 `word/media/*` 原始字节写入文件
- 不经过图片库解码/重新编码
- 保持原扩展名
- 写入后重新读取并计算 SHA-256，与 DOCX 内原始字节比对
- 每个 manifest 条目的 `sha256_verified` 表示校验结果

## manifest 示例

```json
{
  "schema_version": 1,
  "document": "sample_prd.docx",
  "placeholder_format": "{{SHOWDOC_IMAGE_%06d}}",
  "summary": {
    "occurrences": 2,
    "unique_media": 1,
    "duplicates": 1,
    "failed": 0,
    "compatibility": 0,
    "unreferenced_media": 0
  },
  "images": [
    {
      "placeholder": "{{SHOWDOC_IMAGE_000001}}",
      "order": 1,
      "relationship_id": "rIdImg1",
      "source_part": "word/media/image1.png",
      "local_path": "assets/sample_prd-image-000001.png",
      "extension": ".png",
      "mime_type": "image/png",
      "size": 105654,
      "sha256": "e1fdb2948a03bd72fc9966a6f03b657f5c7eac3a299ca7edbb3d675fa9be1df8",
      "sha256_verified": true,
      "is_duplicate": false,
      "duplicate_of": null,
      "alt_text": "示例图片",
      "alt_source": "docPr:descr",
      "is_compatibility_format": false,
      "preview_path": null,
      "preview_status": "not_needed",
      "showdoc_url": null,
      "upload_status": "not_uploaded",
      "replacement_status": "pending",
      "status": "extracted",
      "error": null
    }
  ],
  "unreferenced_media": [],
  "errors": [],
  "notes": [
    "未执行任何上传；showdoc_url 与 upload_status 由人工处理。"
  ]
}
```

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

## 兼容格式

EMF、WMF、TIFF 会保留原始文件；如果本机安装了 Pillow，会额外生成 `*-preview.png`。未安装 Pillow 时 `preview_status` 为 `unavailable`，不会静默忽略。兼容预览只用于显示，原文件始终未重新编码。

## 异常报告

以下情况都会写入 manifest 的 `errors` 或 `unreferenced_media`：

- relationship 不存在
- 外部链接图片
- media 文件缺失
- 读取/写入失败
- SHA-256 校验失败
- `word/media/` 中未被正文引用的文件
- 正文本身已包含 `{{SHOWDOC_IMAGE_` 样式文本

如果图片位于文本框等当前 Markdown 解析器未支持的结构中，图片仍会被提取，但占位符可能没有出现在 Markdown 里；报告中会出现 `image_placeholder_unplaced`。

## 已知限制

- 不执行 ShowDoc 上传或 URL 回填（按约定由人工处理）。
- 浏览器对多图剪贴板支持不一致；工具会依次尝试 Clipboard API 和 HTML 多图模式，仍失败时退化为复制第一张，并提示逐张复制。
- EMF / WMF / TIFF 等浏览器无法解码的格式不能复制为图片，但可以下载原始文件。
- 页眉、页脚中的图片不属于正文，会出现在 `unreferenced_media` 中。
- 文本框、嵌套表格等结构尚未进入 Markdown 渲染时，对应占位符可能未落位，但会报告。
- 多个 DOCX 输出到同一个 `output` 目录时，`assets/manifest.json` 会被后一次运行覆盖；批量处理建议每个文档使用独立输出目录。
- PNG 预览依赖可选的 Pillow。
