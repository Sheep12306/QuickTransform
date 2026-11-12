# QuickTransform

Word（.docx）转 Markdown 的本地工具，面向进销存产品文档。

当前进度：M0 骨架 + 本地网页界面。已支持段落、标题（样式的大纲级别与名称匹配）、加粗/斜体行内格式、转换报告，以及按正文顺序提取 Word 图片并生成 ShowDoc 占位符。

## 运行

本机 Python 位于 `.tools/python312/python.exe`（免安装嵌入式版，无需系统安装）。

```powershell
.tools\python312\python.exe -m w2md convert <文件.docx 或目录> -o <输出目录>
```

网页界面（浏览器里拖入文档即可转换、预览、下载）：

```powershell
.tools\python312\python.exe -m w2md serve --port 8000
```

命令行转换：

```powershell
.tools\python312\python.exe -m w2md convert samples\sample_prd.docx -o samples\out
```

提取图片并按正文顺序生成 ShowDoc 占位符（不执行上传）：

```powershell
.tools\python312\python.exe -m w2md extract-images samples\sample_prd.docx -o output
```

输出：

- `output\<文档名>.md`：图片位置为 `{{SHOWDOC_IMAGE_000001}}` 形式的占位符
- `output\assets\`：按正文顺序提取的原始图片（字节直拷）
- `output\assets\manifest.json`：占位符、relationship id、原始 media 路径、SHA-256、alt 文本、兼容格式状态等

网页版独立图片工具（只展示图片，不生成 Markdown，支持格式筛选、勾选复制、打包下载）：

```text
http://127.0.0.1:8000/word2image.html
```

图片模块说明见 [docs/IMAGE_EXTRACTION.md](docs/IMAGE_EXTRACTION.md)。

## 占位替换工具

把 ShowDoc 返回的图片 URL 按顺序填回 Markdown 占位符：

```text
http://127.0.0.1:8000/placeholder_replace.html
```

支持数量校验、映射确认、手动调整、代码块跳过、新文件输出和 manifest 更新。命令行：

```powershell
.tools\python312\python.exe -m w2md replace-placeholders output\文档.md --showdoc showdoc.md -o output --manifest output\assets\manifest.json
```

详细说明见 [docs/PLACEHOLDER_REPLACE.md](docs/PLACEHOLDER_REPLACE.md)。

## 标题层级识别

标题按以下优先级识别，字号不会覆盖明确的大纲级别或标题样式：

1. 段落 `w:pPr/w:outlineLvl`（0 → H1，1 → H2，以此类推）
2. 段落样式 `w:pStyle`，结合 `word/styles.xml` 的 `outlineLvl`、样式名（`heading 1` / `标题 1` / `一级标题` / `H1`）和 `w:basedOn` 继承
3. 多级编号或正文编号前缀（`1.`、`1.1`、`1.1.1`）
4. 字号 + 加粗，仅在没有任何大纲级别、标题样式和编号时兜底

默认整体下移一级，Word H1 输出为 `##`、H2 输出为 `###`，避免 `#` 在页面中过大；使用 `--heading-offset 0` 可恢复从 `#` 开始。超过六级时输出为 `######`，Word 原始七级及以上会带 `〔H7〕` 标记，并在报告中记录降级。每个标题的识别来源写入 `.report.json` 的 `headings` 字段，来源值为 `outlineLvl`、`style`、`numbering` 或 `font`。

## 测试

```powershell
.tools\python312\python.exe -m unittest discover -s tests -v
```

## 文档

架构设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
