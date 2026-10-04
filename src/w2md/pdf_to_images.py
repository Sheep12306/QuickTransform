"""PDF to images conversion.

Windows uses the built-in PDF renderer via PowerShell; Linux/macOS use
`pdftoppm` (poppler-utils).
"""

import subprocess
import sys
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parent / "pdf_to_images.ps1"
_ALLOWED_FORMATS = {"png", "jpg", "jpeg"}


def convert_pdf_to_images(source, output_dir, image_format="png", dpi=144, timeout=180):
    source = Path(source)
    output_dir = Path(output_dir)
    if not source.is_file():
        raise FileNotFoundError("找不到待转换的 PDF 文件")

    image_format = image_format.lower()
    if image_format not in _ALLOWED_FORMATS:
        raise ValueError("不支持的图片格式")
    if image_format == "jpeg":
        image_format = "jpg"

    output_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        _convert_with_powershell(source, output_dir, image_format, dpi, timeout)
    else:
        _convert_with_pdftoppm(source, output_dir, image_format, dpi, timeout)

    images = sorted(output_dir.glob("page-*." + image_format), key=_page_number)
    if not images:
        raise RuntimeError("PDF 转图片失败：没有生成图片")
    return images


def _page_number(path):
    # "page-001.png" (Windows) / "page-1.png" (pdftoppm) -> 1
    try:
        return int(path.stem.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def _convert_with_powershell(source, output_dir, image_format, dpi, timeout):
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SCRIPT),
            str(source),
            str(output_dir),
            image_format,
            str(dpi),
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "PDF 转图片失败")


def _convert_with_pdftoppm(source, output_dir, image_format, dpi, timeout):
    # pdftoppm 输出 page-1.png / page-2.png …，与 Windows 的 page-001.png 兼容。
    fmt_flag = "-jpeg" if image_format == "jpg" else "-" + image_format
    try:
        completed = subprocess.run(
            [
                "pdftoppm",
                fmt_flag,
                "-r",
                str(dpi),
                str(source),
                str(output_dir / "page"),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "服务器缺少 pdftoppm（poppler-utils）。请在服务器执行："
            "sudo apt-get install -y poppler-utils"
        )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or "PDF 转图片失败")
