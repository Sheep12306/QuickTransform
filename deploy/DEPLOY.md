# QuickTransform 服务器部署指南（Linux + FinalShell）

## 0. 先理解一件事

QuickTransform **不是纯静态网页**，而是一个 Python Web 服务（用 Python 标准库 `http.server`，前端页面在 `src/w2md/server/static/`）。

把文件「拖进 FinalShell」只是把代码上传上去，要让网站真正跑起来，服务器上还必须完成三件事：

1. 安装 Python 3.11+
2. 安装依赖包（`lxml`、`openpyxl`、`xlrd`、`python-docx`、`pdf2docx`）
3. 启动服务进程并保持常驻

下面按顺序来。

---

## 1. 上传哪些文件（FinalShell 拖拽时排除这些）

FinalShell → 连接服务器 → 打开文件管理（SFTP），在服务器上新建目录：

```
/opt/quicktransform
```

把项目内容拖进去。**这几个目录不要拖**（本机专用 / 体积大 / 无用）：

| 排除项 | 原因 |
| --- | --- |
| `.tools/` | 329MB 的 Windows 嵌入式 Python，Linux 服务器用不了 |
| `.git/` | 本地 Git 历史，服务器不需要 |
| `__pycache__/`、`*.pyc` | 编译缓存 |
| `samples/out/` | 转换输出的临时文件 |

> 也可以用命令在服务器上直接 `git clone`，但既然你习惯 FinalShell，拖拽即可。

---

## 2. 安装依赖

**Ubuntu / Debian**（阿里云、腾讯云默认系统多为 Ubuntu）：

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv poppler-utils
sudo pip3 install -r /opt/quicktransform/deploy/requirements.txt
```

**CentOS / 阿里云 Linux / 龙蜥**：把上面 `apt-get` 换成 `yum`（`python3`、`python3-pip` 包名相同）。

---

## 3. 启动服务

**推荐：一键脚本**（会装依赖 + 注册 systemd 开机自启）：

```bash
sudo bash /opt/quicktransform/deploy/deploy.sh
```

**或者手动临时跑起来**（测试用，关掉终端就停）：

```bash
cd /opt/quicktransform
PYTHONPATH=src nohup python3 -m w2md serve --host 0.0.0.0 --port 8000 > /var/log/quicktransform.log 2>&1 &
```

---

## 4. 访问

浏览器打开：

```
http://<服务器公网IP>:8000
```

⚠️ 云服务器需要在**安全组/防火墙**里放行 `8000` 端口，否则外网连不上。

---

## 5. 常驻 + 开机自启（systemd）

`deploy.sh` 已自动完成。手动注册方式：

```bash
sudo cp /opt/quicktransform/deploy/quicktransform.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quicktransform
systemctl status quicktransform   # 查看运行状态
systemctl restart quicktransform  # 重启
```

---

## 6. 绑定域名 + HTTPS（可选，用 nginx 反代）

安装 nginx 后，`/etc/nginx/conf.d/quicktransform.conf`：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 100m;   # 允许上传较大的 docx/pdf

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;  # 大文件转换较慢，超时给足
    }
}
```

然后 `sudo nginx -t && sudo systemctl reload nginx`。HTTPS 可用 `certbot --nginx` 免费签发证书。

---

## 7. ⚠️ PDF 转图片功能在 Linux 上的限制

目前「PDF → 图片」的实现调用的是 **Windows PowerShell**（`src/w2md/pdf_to_images.ps1`），在 Linux 服务器上会失败。

- 其余功能（docx→markdown、excel→csv/json、PDF→Word）均**跨平台**，Linux 上正常。
- 若服务器上也需要「PDF→图片」，需要把这段改成调用 Linux 的 `pdftoppm`（poppler-utils，上文已安装）。这属于代码改动，可让开发者帮忙加一段 Linux 兼容逻辑。

---

## 8. 更新版本

本地改完代码后，FinalShell 重新拖拽覆盖 `/opt/quicktransform` 里的文件（同样排除 `.tools/` 等），然后：

```bash
sudo systemctl restart quicktransform
```

---

## 常见问题

- **端口访问不了**：先查安全组是否放行 8000；再查 `systemctl status quicktransform` 是否 running；最后看 `journalctl -u quicktransform -n 50`。
- **`pip install lxml` 报错**：用 `pip3 install lxml` 走预编译 wheel；若提示缺编译环境，先 `apt-get install -y build-essential python3-dev libxml2-dev libxslt1-dev`。
- **上传大文件失败**：确认 nginx 的 `client_max_body_size` 已调大（见第 6 节）。
