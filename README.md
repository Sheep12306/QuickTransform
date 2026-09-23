# QuickTransform

Word（.docx）转 Markdown 的本地工具，面向进销存产品文档。

当前进度：M0 骨架 + 本地网页界面。已支持段落、标题（样式的大纲级别与名称匹配）、加粗/斜体行内格式、转换报告。

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

## 测试

```powershell
.tools\python312\python.exe -m unittest discover -s tests -v
```

## 文档

架构设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。
