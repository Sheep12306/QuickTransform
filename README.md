# QuickTransform

Word（.docx）转 Markdown 的本地工具，面向进销存产品文档。

当前进度：M0 骨架 + 本地网页界面。已支持段落、标题（样式的大纲级别与名称匹配）、加粗/斜体行内格式、转换报告、按正文顺序提取 Word 图片、图片兼容性预检（EMF/WMF/TIFF 转 PNG、超大 PNG 生成预览）、生成 manifest，导入浏览器扩展的上传记录、只替换成功图片并输出缺失清单，以及特殊图片人工 URL 回填与最终占位符残留检查。

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

- `output\<文档名>.md`：正常图片为 `{{SHOWDOC_IMAGE_000001}}` 占位符；不支持/超限/转换失败的图片使用特殊占位符
- `output\assets\original\`：按正文顺序提取的原始图片（字节直拷）
- `output\assets\upload\`：上传副本（普通图片原样复制，EMF/WMF/TIFF 转 PNG，超大图片生成预览）
- `output\assets\manifest.json`：占位符、`occurrence_id`、原始/上传路径、`source_sha256` / `upload_sha256`、兼容性分类、章节与上下文

网页版独立图片工具（只展示图片，不生成 Markdown，支持格式筛选、勾选复制、打包下载）：

```text
http://127.0.0.1:8000/word2image.html
```

图片模块说明见 [docs/IMAGE_EXTRACTION.md](docs/IMAGE_EXTRACTION.md)。

## 特殊图片处理与检查

只处理「上传结果导入」自动回填后残留的 `unsupported` / `oversized` / `conversion_failed` 特殊图片。左侧显示 Markdown，右侧显示 manifest 解析出的特殊图片清单；点击条目可定位并高亮对应占位符，每项独立填写 ShowDoc URL：

```text
http://127.0.0.1:8000/special_images.html
```

页面检查普通占位符残留、特殊图片待处理数量、URL 有效性、`occurrence_id` 唯一性和最终占位符残留。输入为 Markdown + `manifest.json`，不接受 `upload_result.json`；普通图片统一由「上传结果导入」处理。命令行：

```powershell
.tools\python312\python.exe -m w2md replace-special-images output\文档.md --manifest output\assets\manifest.json --urls special_urls.json -o output\final
```

详细说明见 [docs/SPECIAL_IMAGES.md](docs/SPECIAL_IMAGES.md)。

## 上传结果导入（推荐）

浏览器扩展「ShowDoc 图片上传记录器」会监听每张图片的上传请求并导出 `upload_result.json`。本工具按 `occurrence_id` / 占位符 / `upload_sha256` 显式映射，只替换真正成功的图片；失败图片保留占位符，EMF 转换副本使用 `upload_sha256` 匹配，特殊占位符保持不动：

```text
http://127.0.0.1:8000/upload_result.html
```

支持部分成功、严格、只补齐遗留占位符三种模式，输出最终 Markdown、`missing_images.csv`、`replacement_report.json` 和可选的 `missing_images.html`。命令行：

```powershell
.tools\python312\python.exe -m w2md apply-upload-result output\文档.md `
  --upload-result upload_result.json `
  --manifest output\assets\manifest.json `
  -o output\final --mode partial --confirm-partial
```

详细说明见 [docs/UPLOAD_RESULT.md](docs/UPLOAD_RESULT.md)。

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
