#!/usr/bin/env bash
set -euo pipefail

# QuickTransform Linux 一键部署
# 支持 Ubuntu/Debian、Alibaba Cloud Linux / CentOS / Anolis
# 前提：已把整个项目上传到 /opt/quicktransform
# 用法：sudo bash /opt/quicktransform/deploy/deploy.sh

APP_DIR=/opt/quicktransform
SERVICE=quicktransform
PORT=8000
PY=""

if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 执行：sudo bash ${APP_DIR}/deploy/deploy.sh" >&2
  exit 1
fi

echo "==> 1/4 安装 Python 3.9+ 与系统工具"
if command -v dnf >/dev/null 2>&1; then
  PM=dnf
elif command -v yum >/dev/null 2>&1; then
  PM=yum
else
  PM=""
fi

if [ -n "${PM}" ]; then
  # RHEL / Alibaba Cloud Linux / CentOS / Anolis：默认 python3 常为 3.6，需另装新版本
  if ${PM} install -y python3.11 python3.11-pip >/dev/null 2>&1; then
    PY=python3.11
  elif ${PM} install -y python3.9 python3.9-pip >/dev/null 2>&1; then
    PY=python3.9
  else
    echo "无法安装 python3.9/3.11，请检查软件源后重试" >&2
    exit 1
  fi
  ${PM} install -y poppler-utils || true
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3 python3-pip python3-venv poppler-utils
  PY=python3
else
  echo "未识别到包管理器（dnf/yum/apt-get），请手动安装 Python 3.9+ 与 pip" >&2
  exit 1
fi

echo "==> 2/4 安装 Python 依赖（${PY}）"
"${PY}" -m pip install -r "${APP_DIR}/deploy/requirements.txt"

echo "==> 3/4 生成并注册 systemd 服务"
sed "s|__PYTHON__|/usr/bin/${PY}|" "${APP_DIR}/deploy/quicktransform.service" \
  > /etc/systemd/system/${SERVICE}.service

echo "==> 4/4 启动服务"
systemctl daemon-reload
systemctl enable --now "${SERVICE}"
systemctl status "${SERVICE}" --no-pager || true

echo ""
echo "部署完成。访问 http://<服务器公网IP>:${PORT}"
echo "请确认云服务器安全组已放行 ${PORT} 端口。"
