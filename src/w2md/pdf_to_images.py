"""PDF to images conversion using the built-in Windows PDF renderer."""

import subprocess
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

    images = sorted(output_dir.glob("page-*." + image_format))
    if not images:
        raise RuntimeError("PDF 转图片失败：没有生成图片")
    return images
