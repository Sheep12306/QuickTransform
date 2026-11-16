# 导入 ShowDoc 上传结果并部分替换占位符

本模块把浏览器扩展「ShowDoc 图片上传记录器」导出的 `upload_result.json` 导入转换工具，只把**真正上传成功**的图片替换为 ShowDoc URL。

转换工具不登录 ShowDoc、不保存 Cookie / Token、不调用 ShowDoc 接口。浏览器扩展是独立交付物，两边只通过 JSON 文件交互。

## 为什么不能按成功 URL 顺序替换

ShowDoc 返回的 URL 是随机文件名，不包含原图序号。如果 400 张图片中有 36 张失败，按“第 N 个成功 URL + 第 N 个占位符”压缩匹配，从第一张失败图片开始，后面的 URL 会全部错位。

本工具只接受显式映射：

```text
occurrence_id / placeholder
  -> manifest 中的 upload_sha256（上传副本哈希）
  -> 该 upload_sha256 对应的成功 URL
```

普通图片的 `upload_sha256 == source_sha256`；EMF/WMF/TIFF 转换图片的 `upload_sha256` 是转换后 PNG 的哈希。浏览器扩展上传的是上传副本，因此必须用 `upload_sha256` 匹配。

失败、未上传、无法匹配的图片不会占用任何 URL，后续图片也不会前移。`unsupported` / `oversized` / `conversion_failed` 图片使用特殊占位符，不进入自动替换流程。嵌入的 Word/视频/HTML/OLE 对象（`embedded`）也不参与替换，工具只提示人工在 ShowDoc 上传。

## 网页入口

启动本地服务后打开：

```text
http://127.0.0.1:8000/upload_result.html
```

或从首页点击「上传结果导入」。

页面操作：

1. 选择带占位符的 Markdown（Word 转 Markdown / 图片提取生成的 `.md`）。
2. 选择浏览器扩展导出的 `upload_result.json`。
3. 建议选择同一批图片的 `manifest.json`，用于交叉校验 `document_id`、SHA-256、原图数量和未上传图片。
4. 可选选择原图或上传副本文件，缺失清单和 `missing_images.html` 会显示缩略图。
5. 选择处理模式：
   - **部分成功**（默认）：成功替换，失败 / 未上传 / 无法匹配的图片保留原占位符。
   - **严格**：只有全部预期图片都成功、manifest 中每个占位符都出现在 Markdown 正文、且没有清单外占位符 / 意外上传时才生成。
   - **只补齐遗留占位符**：只处理当前 Markdown 中仍存在的占位符，已替换的图片不重新上传、不修改。
6. 点击「预览替换结果」，逐张查看“成功，替换为 URL / 失败，保留占位符”。
7. 点击「生成最终 Markdown」。如果仍有缺失，页面会显示缺失数量并再次确认。
8. 下载最终 Markdown、`missing_images.csv`、`replacement_report.json` 和可选的 `missing_images.html`。

## 命令行

```powershell
.tools\python312\python.exe -m w2md apply-upload-result output\文档.md `
  --upload-result upload_result.json `
  --manifest output\assets\manifest.json `
  -o output\final `
  --mode partial `
  --confirm-partial
```

参数：

- `--mode partial|strict|fill-remaining`：默认 `partial`。
- `--allow-mismatch`：`document_id`、占位符或 SHA-256 不一致时继续。不一致的图片不会使用 URL，仍保留占位符，报告中标记为需要人工确认。
- `--confirm-partial`：部分成功模式仍有缺失时，必须加此参数才会生成。没有该参数时返回码为 `2`。
- `--assets-dir`：可选图片目录。`missing_images.html` 会从这里读取缺失图片并嵌入缩略图；不提供时会尝试 `manifest.json` 所在的 `assets/` 和其上一级目录。
- `--no-html`：不生成可选的 `missing_images.html`。

输出：

```text
output/final/
  final_markdown_YYYYMMDD_HHMMSS.md
  missing_images.csv
  replacement_report.json
  missing_images.html
```

不会覆盖输入的 Markdown、`manifest.json` 或原始图片。

## upload_result.json 兼容状态

每个图片位置最终归入以下状态之一：

| 状态 | 含义 |
| --- | --- |
| `success` | 取得非空 `http(s)` URL，且 `response_success` 不是 0/false |
| `failed` | 请求发出但失败；HTTP 200 但 `response_success=0` 也归为失败 |
| `not_uploaded` | manifest 中有原图，但没有任何上传请求 |
| `pending` / `interrupted` | 上传未完成，不能当作成功 |
| `unmatched` | 上传记录与原图的 `occurrence_id` / 占位符 / `upload_sha256` 不一致，或无法匹配 |
| `unexpected_upload` | 上传记录中的图片不在当前 manifest 内 |
| `unsupported` | manifest 标记为不支持，保留特殊占位符 |
| `oversized` | manifest 标记为超限，保留特殊占位符 |
| `conversion_failed` | manifest 标记为转换失败，保留特殊占位符 |
| `embedded` | 嵌入的 Word/视频/HTML/OLE 对象，不替换，仅提醒人工上传 |

`uploads` 中的 `status` 可以为 `success`、`failed`、`not_uploaded`、`unmatched`、`pending`、`interrupted` 等。工具会重新检查 `response.success`，不会仅凭 HTTP 200 或 `status=success` 判断成功。

`missing` 数组中的记录会和 `uploads` 合并；同一条记录如果同时标记成功和失败，以成功为准并给出警告。特殊图片对应的上传记录会被记录到 `ignored_special_uploads`，不会用于替换。

## 显式映射规则

1. 优先按 `occurrence_id` 匹配 manifest 中的正文位置。
2. 其次按 `placeholder` 匹配。
3. 上传记录没有位置信息时，才按 `upload_sha256` 匹配唯一的普通图片。
4. 同一 `upload_sha256` 对应多个正文位置时（同一图片重复出现），只要有一个成功 URL，就复用到所有相同哈希的位置；每个位置仍保留自己的 `occurrence_id` 和占位符。
5. 匹配到位置后，会交叉检查 `occurrence_id`、`placeholder`、`sha256`（对比 manifest 的 `upload_sha256`）；任一不一致都会阻止自动替换，除非显式允许不一致。
6. 特殊图片（`unsupported` / `oversized` / `conversion_failed`）不参与匹配和替换，即使上传记录成功也保持特殊占位符。
7. 禁止按 ShowDoc URL 出现顺序、图片体积、请求完成时间或随机文件名重新编号。

## 替换规则

- 成功格式：`![alt文本](ShowDoc图片URL)`，alt 优先使用 manifest 的 `alt_text`。
- 只替换正文中的普通目标占位符；fenced code block、缩进代码块和行内代码中的同名文本不替换。
- `unsupported` / `oversized` / `conversion_failed` 特殊占位符保持不动。
- 保留换行、CRLF、缩进、列表、表格、引用块。
- 不覆盖原 Markdown，输出新文件。
- 最终文件不允许包含 `data:image` Base64。

## 生成前后校验

生成前：

- manifest 总数、普通图片数、特殊图片数
- Markdown 中普通占位符数量、特殊占位符数量
- `upload_result.json` 中 `uploads` / `missing` 记录数量
- 成功、失败、未上传、待定/中断、无法匹配、意外上传数量
- 声明统计与实际记录是否一致（`expected_count`、`detected_request_count`、`success_unique_count` 等）

生成后再次扫描：

- 成功图片的普通占位符应全部消失
- 失败、未上传、待定/中断、无法匹配的普通占位符仍存在
- 特殊占位符数量与文本保持不变，不能被替换
- 不应存在 `data:image`
- 成功图片重复位置应使用同一 URL（如果 extension 为同一上传副本哈希上传了不同 URL，会给出提示）
- 不应出现未预期占位符

出现异常时仍会保留中间 Markdown，并把错误写入 `replacement_report.json`，不会只显示“失败”。

## 缺失清单

`missing_images.csv` 包含：

```text
序号, occurrence_id, 占位符, 原始文件名, 原始路径, 上传文件名, 上传路径,
大小, SHA-256, 原始SHA-256, 上传SHA-256, 章节, 上下文前置文字,
上下文后置文字, 状态, 失败原因, 是否在Markdown中, 行号
```

`SHA-256` 优先取上传副本哈希；`原始SHA-256` 和 `上传SHA-256` 分别记录原始文件和上传副本。特殊图片也会出现在清单中，状态为 `unsupported` / `oversized` / `conversion_failed`。

`missing_images.html`（可选）用表格展示同样内容，并在选择了原图或上传副本时嵌入缩略图。

## 只补齐遗留占位符

适用于“400 张里失败 36 张”的场景：

1. 先用部分成功模式生成最终 Markdown，成功图片已经替换。
2. 用户只重新上传缺失的 36 张。
3. 浏览器扩展只记录这 36 条新上传结果。
4. 打开本工具，选择当前最终 Markdown、新的 `upload_result.json` 和原 `manifest.json`。
5. 选择「只补齐遗留占位符」，生成新的 Markdown。

工具只替换当前 Markdown 中仍存在的普通占位符；已经成功的图片不会重新上传，也不会被修改；特殊占位符继续保持不动。

普通图片补齐后，如果仍有 `unsupported` / `oversized` / `conversion_failed` 特殊占位符，请转到 [特殊图片处理与检查](SPECIAL_IMAGES.md) 逐张填写 URL。

## oversized 图片的行为

`oversized` 图片会生成预览上传副本（优先 PNG，必要时 JPEG），manifest 中记录 `upload_file` 和 `upload_sha256`，但按约定保留 `{{SHOWDOC_OVERSIZED_IMAGE_...}}` 特殊占位符，不进入自动替换流程。

如果业务上希望自动替换 oversized 预览副本，需要先调整阈值（`--max-upload-mb`、`--max-image-dimension`）让图片重新分类为 `supported`，或由人工上传后手工替换。

## 已知限制

- 不登录 ShowDoc、不自动上传；上传由浏览器扩展和用户完成。
- 未提供 manifest 时仍可按 `upload_result.json` 中的记录做部分替换，但无法发现“有原图却完全没有上传记录”的图片，缺失清单可能不完整，页面和报告会明确提示。
- 上传记录中的 `sha256` 必须对应上传副本（即 manifest 的 `upload_sha256`）。如果扩展记录的是原始图片哈希，转换图片会触发哈希不一致确认流程。
- 浏览器剪贴板可能把 JPEG/GIF 重新编码为 PNG。此时扩展记录的实际上传哈希与 manifest 的 `upload_sha256` 不一致，会进入 `unmatched` 或需要人工确认。建议直接从 `assets/upload/` 选择文件上传，避免剪贴板二次编码。
- `section` / `context_before` / `context_after` 是尽力而为的定位信息；文本框、嵌套结构中的图片可能无法准确取到上下文。
- `missing_images.html` 只对浏览器能解码的图片生成缩略图；EMF、WMF 等格式下载原文件后人工查看。
- 如果用户手工修改了 Markdown 中的占位符，修改后的占位符会被列为“不在 manifest 内”，对应原图会被列为“Markdown 中缺少占位符”，工具不会擅自补回。
- 特殊占位符（unsupported / oversized / conversion_failed）不会自动替换，即使图片已人工上传；请使用 [特殊图片处理与检查](SPECIAL_IMAGES.md) 手工填写 URL。
