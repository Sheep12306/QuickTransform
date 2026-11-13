#!/usr/bin/env python3
"""Raise nginx upload/timeout limits for QuickTransform.

Run on the server after deployment:

    python3 /opt/quicktransform/deploy/tune_nginx.py

The script is idempotent. It finds the nginx config containing the
QuickTransform domain or the 127.0.0.1:8080 upstream, raises
``client_max_body_size`` to 200m, ensures proxy timeouts are long enough for
large Word files, then validates and reloads nginx.
"""

import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path


SEARCH_ROOTS = [
    "/www/server/panel/vhost/nginx",
    "/www/server/nginx/conf",
    "/etc/nginx",
    "/usr/local/nginx/conf",
]
MARKERS = [
    "quicktransform.kuaikeli.tech",
    "127.0.0.1:8080",
    "localhost:8080",
]
UPLOAD_DIRECTIVE = "client_max_body_size 200m;"
TIMEOUT_DIRECTIVES = [
    ("proxy_read_timeout", "proxy_read_timeout 300s;"),
    ("proxy_send_timeout", "proxy_send_timeout 300s;"),
    ("proxy_connect_timeout", "proxy_connect_timeout 60s;"),
]
NGINX_CANDIDATES = [
    "/www/server/nginx/sbin/nginx",
    "/usr/sbin/nginx",
    "/usr/local/nginx/sbin/nginx",
]


def find_nginx():
    for candidate in NGINX_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("nginx")
    if found:
        return found
    return "nginx"


def find_configs():
    seen = set()
    for root in SEARCH_ROOTS:
        base = Path(root)
        if not base.is_dir():
            continue
        for path in base.rglob("*.conf"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if not any(marker in text for marker in MARKERS):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield path, text


def tune_text(text):
    changed = False

    for key, directive in [("client_max_body_size", UPLOAD_DIRECTIVE)] + TIMEOUT_DIRECTIVES:
        pattern = re.compile(r"(?m)^(\s*)" + key + r"\s+[^;]+;")
        new_text, count = pattern.subn(r"\1" + directive, text)
        if count:
            if new_text != text:
                changed = True
            text = new_text

    missing = []
    if "client_max_body_size" not in text:
        missing.append(UPLOAD_DIRECTIVE)
    for key, directive in TIMEOUT_DIRECTIVES:
        if key not in text:
            missing.append(directive)

    if missing:
        match = re.search(r"(?m)^(\s*)server\s*\{", text)
        if match is None:
            raise RuntimeError("未找到 server { } 配置块")
        indent = match.group(1) + "    "
        insertion = "\n" + "\n".join(indent + item for item in missing) + "\n"
        text = text[: match.end()] + insertion + text[match.end() :]
        changed = True

    return text, changed


def main():
    nginx = find_nginx()
    configs = list(find_configs())
    if not configs:
        print("未找到包含 QuickTransform 的 nginx 配置")
        for root in SEARCH_ROOTS:
            print("  searched:", root)
        return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    changed_files = []
    for path, text in configs:
        try:
            new_text, changed = tune_text(text)
        except RuntimeError as exc:
            print("{0}: {1}".format(path, exc))
            continue
        if not changed:
            print("unchanged:", path)
            continue
        backup = path.with_name(path.name + ".qt-backup-" + stamp)
        shutil.copy2(str(path), str(backup))
        path.write_text(new_text, encoding="utf-8")
        changed_files.append((path, backup))
        print("updated:", path, "backup:", backup)

    if not changed_files:
        print("nginx 配置已经是目标值，无需修改")
        return 0

    result = subprocess.run([nginx, "-t"])
    if result.returncode != 0:
        for path, backup in changed_files:
            shutil.copy2(str(backup), str(path))
        print("nginx -t 失败，已回滚配置")
        return 1

    reload_result = subprocess.run([nginx, "-s", "reload"])
    if reload_result.returncode != 0:
        print("nginx reload 失败")
        return 1

    print("nginx reload 完成，client_max_body_size=200m，proxy timeout=300s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("tune_nginx failed:", exc)
        sys.exit(1)
