# 特殊图片处理与检查

处理「上传结果导入」自动回填之后，Markdown 中仍然残留的特殊图片占位符：

```text
{{SHOWDOC_UNSUPPORTED_IMAGE_000012}}
{{SHOWDOC_OVERSIZED_IMAGE_000034}}
{{SHOWDOC_CONVERSION_FAILED_IMAGE_000056}}
```

这些图片在 manifest 中的 `compatibility` 为 `unsupported` / `oversized` / `conversion_failed`，不会进入自动上传和自动替换流程。人工把它们上传到 ShowDoc 后，在本页面逐张填写 URL。

嵌入的 Word/视频/HTML/OLE 对象使用 `{{SHOWDOC_EMBEDDED_...}}` 占位符，本页面**不处理**这类对象，只会在提示中列出，需要直接在 ShowDoc 手动上传原文件。

> 本页面**只处理特殊图片**，不处理普通占位符 `{{SHOWDOC_IMAGE_000001}}`，也不接受 `upload_result.json`。
> 普通图片请使用 [上传结果导入](UPLOAD_RESULT.md)。

## 使用场景

```text
Word / 图片提取
  -> 带普通 + 特殊占位符的 Markdown + manifest.json
  -> 上传结果导入：只替换上传成功的普通图片
  -> 特殊图片处理：人工上传特殊图片并填写 URL
  -> 最终 Markdown（正文中不再有占位符）
```

## 网页入口

```text
http://127.0.0.1:8000/special_images.html
```

或从首页点击「特殊图片处理」。

## 页面操作

1. 在左侧拖入 / 选择 `upload_result` 生成的 Markdown，或直接粘贴。普通图片应当已经回填完成。
2. 在右侧拖入 / 选择同一批图片的 `manifest.json`。
3. 右侧按正文顺序列出 manifest 中的特殊图片：
   - 序号、`occurrence_id`、占位符
   - 兼容性分类（不支持格式 / 图片超限 / 转换失败）
   - 原始文件名、首次出现行号、出现次数
   - 每项独立的 ShowDoc URL 输入框
4. 点击任意条目（或「定位」按钮），左侧 Markdown 会滚动到对应行并选中、高亮该占位符。
5. 逐张填写 URL。输入后自动重新检查，`待处理` 数量实时更新。
6. 全部填写且检查通过后，点击「生成最终 Markdown」。
7. 下载最终 Markdown、更新后的 manifest 和检查报告。

## 检查项

页面顶部固定展示以下检查：

| 检查 | 通过条件 | 不通过时的行为 |
| --- | --- | --- |
| 普通占位符残留 | 正文中没有 `{{SHOWDOC_IMAGE_...}}` | 阻止生成，提示先使用「上传结果导入」 |
| 特殊图片待处理 | 正文中的特殊图片都已填写有效 URL | 阻止生成，并列出待处理占位符 |
| URL 有效性 | 所有已填写 URL 为 `http://` / `https://`，不含空白和 `data:` | 阻止生成，标出非法条目 |
| occurrence_id 唯一性 | manifest 中 `occurrence_id` 不重复 | 阻止生成，列出重复项 |
| 清单外特殊占位符 | 正文中没有 manifest 未包含的特殊占位符 | 阻止生成 |
| 最终占位符残留 | 生成后的正文中没有任何占位符 | 不输出最终 Markdown |

补充规则：

- 代码块（fenced / 缩进）和行内代码中的占位符按 Markdown 规则不替换，只在警告中提示。
- 表格、列表、引用块中的特殊占位符会原位替换。
- 保留原始换行（包括 CRLF）、缩进和文档结构。
- 最终 Markdown 不允许出现 `data:image` Base64。
- 普通图片的 `{{SHOWDOC_IMAGE_...}}` 永远不会被本页面替换。

## 输入与输出

输入：

- Markdown：上传结果导入后的 `.md`
- `manifest.json`：图片提取生成的 manifest，至少包含 `sequence`、`occurrence_id`、`placeholder`、`compatibility`

不接受：

- `upload_result.json`：普通图片回填统一由「上传结果导入」完成

输出：

```text
<文档名>.special.md
<文档名>.manifest.special.json
<文档名>.special.report.json
```

更新后的 manifest 会为已处理特殊图片写入：

```json
{
  "showdoc_url": "https://...",
  "upload_status": "url_received",
  "replacement_status": "replaced",
  "special_url_manual": true
}
```

并新增汇总：

```json
{
  "special_replacement": { "matched": 3, "pending": 0, "total": 3 }
}
```

## 命令行

```powershell
.tools\python312\python.exe -m w2md replace-special-images output\文档.md `
  --manifest output\assets\manifest.json `
  --urls special_urls.json `
  -o output\final
```

`--urls` 支持两种格式：

```json
{
  "{{SHOWDOC_UNSUPPORTED_IMAGE_000012}}": "https://doc.bizgo.com/Public/Uploads/a.png"
}
```

```json
[
  {
    "placeholder": "{{SHOWDOC_UNSUPPORTED_IMAGE_000012}}",
    "url": "https://doc.bizgo.com/Public/Uploads/a.png"
  }
]
```

输出文件与网页版相同。校验不通过时返回码为 `1`，不会写出最终 Markdown。

## 常见问题

**普通占位符还存在怎么办？**

先用「上传结果导入」的「只补齐遗留占位符」模式重试失败图片。本页面不会替普通图片补 URL。

**特殊图片在 Markdown 中找不到？**

如果它只出现在代码块中，页面会标记「仅出现在代码块」，生成时保持原样；如果正文中确实没有该占位符，条目会显示「Markdown 中无占位符」，不影响其他图片处理。

**manifest 中 occurrence_id 重复怎么办？**

说明 manifest 来自异常提取结果。请重新执行图片提取，或在 manifest 中修正 `occurrence_id` 后再处理；本页面不会猜测重复项的归属。

**特殊图片之后又改动了 Markdown 怎么办？**

重新加载 Markdown 和 manifest，页面会重新扫描并保留已填写的 URL（按占位符匹配）。
