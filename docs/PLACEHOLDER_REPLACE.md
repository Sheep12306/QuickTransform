# 占位替换工具（旧模式）

把 ShowDoc 返回的图片 URL 按顺序填回 Markdown 中的 `{{SHOWDOC_IMAGE_000001}}` 占位符。

> **部分图片上传失败时请不要使用本页面。** 本页面按成功 URL 的出现顺序建立映射；只要中间有一张失败，后面的 URL 就会整体错位。请使用 [上传结果导入](UPLOAD_RESULT.md)，它按 `occurrence_id / 占位符 / upload_sha256` 显式映射，失败图片与 `unsupported` / `oversized` / `conversion_failed` 特殊占位符都会保留，且不会影响后续图片。

## 使用场景

1. 用 Word 转 Markdown 的「占位符」模式生成带占位符的 Markdown。
2. 人工按顺序把图片粘贴到 ShowDoc。
3. 复制 ShowDoc 左侧的 Markdown 源码。
4. 打开「占位替换工具」，粘贴两份 Markdown，必要时上传 `manifest.json` 和图片文件。
5. 校验数量，确认映射，生成新的 Markdown。

工具不会覆盖原 Markdown，也不会修改原始图片。

## 网页入口

启动本地服务后打开：

```text
http://127.0.0.1:8000/placeholder_replace.html
```

或从首页点击「占位替换工具」。

页面支持：

- 读取带占位符的 Markdown 文件或直接粘贴
- 读取 ShowDoc Markdown 源码
- 可选上传 `manifest.json` 显示缩略图、alt 文本
- 可选上传图片文件用于映射表缩略图
- 按顺序自动建立占位符 → URL 映射
- 手动调整每个占位符对应的 URL
- 校验占位符数量、manifest 图片数量、ShowDoc URL 数量
- 生成并下载 `.replaced.md`
- 下载更新后的 manifest
- 下载替换报告

## 命令行

```powershell
.tools\python312\python.exe -m w2md replace-placeholders output\文档.md `
  --showdoc showdoc.md `
  -o output `
  --manifest output\assets\manifest.json
```

可选参数：

- `--mapping mapping.json`：手动映射文件

映射文件格式：

```json
[
  {
    "placeholder": "{{SHOWDOC_IMAGE_000001}}",
    "url": "https://doc.bizgo.com/Public/Uploads/a.png"
  }
]
```

输出：

```text
output/文档.replaced.md
output/文档.manifest.replaced.json
output/文档.replace.report.json
```

如果数量校验不通过，不会生成 `.replaced.md`。

## 校验规则

生成最终 Markdown 前必须满足：

```text
Markdown 中可替换占位符数量
= manifest 中图片数量（如果提供了 manifest）
= ShowDoc 源码中检测到的图片 URL 数量
```

不一致时停止生成，并明确指出：

- 哪些占位符缺少 URL
- 哪些 URL 是多余的
- manifest 数量与占位符数量是否一致
- URL 是否非法（非 http/https、data:image 等）

## 替换规则

- 使用显式 token → URL 映射，不依赖“替换第 N 个括号”
- 替换格式：`![alt文本](ShowDoc图片URL)`
- alt 优先使用 manifest 的 `alt_text`，没有则使用 `图片N`
- 只替换正文中的占位符
- 不替换 fenced code block、缩进代码块、行内代码中的占位符
- 保留原有换行、缩进、列表、表格结构
- 最终 Markdown 不允许包含 `data:image` Base64

## 重复图片

同一媒体文件在文档中重复出现时，每个出现位置仍有独立占位符。映射表允许把多个占位符指向同一个 ShowDoc URL；这不会破坏校验。

## 已知限制

- ShowDoc 源码中的图片必须使用 Markdown 图片语法 `![alt](url)`；HTML `<img>` 不作为 URL 来源。
- 不支持相对 URL 或非 http/https URL，检测到会阻止生成。
- 缩略图需要同时上传 `manifest.json` 和对应图片文件；仅上传 manifest 时映射表仍可使用，但不显示缩略图。
- 只修改 Markdown 中的占位符，不自动上传 ShowDoc。
