#!/usr/bin/env bash
set -euo pipefail

# QuickTransform Linux 一键部署（Ubuntu/Debian）
# 前提：已把整个项目上传到 /opt/quicktransform
# 用法：sudo bash /opt/quicktransform/deploy/deploy.sh

APP_DIR=/opt/quicktransform
SERVICE=quicktransform
PORT=8000

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 执行：sudo bash ${APP_DIR}/deploy/deploy.sh" >&2
  exit 1
fi

echo "==> 1/3 安装系统包（python3 / pip / venv / poppler-utils）"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3 python3-pip python3-venv poppler-utils
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip poppler-utils
else
  echo "未识别到 apt-get 或 yum，请手动安装 python3 与 pip" >&2
  exit 1
fi

echo "==> 2/3 安装 Python 依赖"
python3 -m pip install -r "${APP_DIR}/deploy/requirements.txt"

echo "==> 3/3 注册并启动 systemd 服务"
cp "${APP_DIR}/deploy/quicktransform.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now "${SERVICE}"
systemctl status "${SERVICE}" --no-pager || true

echo ""
echo "部署完成。访问 http://<服务器公网IP>:${PORT}"
echo "请确认云服务器安全组已放行 ${PORT} 端口。"
