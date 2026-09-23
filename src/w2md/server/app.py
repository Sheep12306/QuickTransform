"""Stdlib-only local web server for the converter UI."""

import io
import json
import tempfile
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from ..config import Config
from ..excel2csv import convert_excel_to_csvs
from ..excel2json import convert_excel_to_json
from ..pdf_to_images import convert_pdf_to_images
from ..pdf_to_word import convert_pdf_to_word
from ..pipeline import convert


STATIC_DIR = Path(__file__).resolve().parent / "static"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".md": "text/markdown; charset=utf-8",
    ".zip": "application/zip",
}

_JOBS = {}
_PDF_IMAGE_JOBS = {}
_PDF_WORD_JOBS = {}
_EXCEL_JOBS = {}
_EXCEL_JSON_JOBS = {}


class Handler(BaseHTTPRequestHandler):
    server_version = "QuickTransform/0.1"

    def _send_bytes(self, data, ctype, status=200, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/assets/"):
            return self._serve_asset(path)
        if path.startswith("/api/download/"):
            return self._serve_download(path)
        if path.startswith("/api/pdf2image/files/"):
            return self._serve_pdf_image(path)
        if path.startswith("/api/pdf2image/download/"):
            return self._serve_pdf_images_zip(path)
        if path.startswith("/api/pdf2word/download/"):
            return self._serve_pdf_word(path)
        if path.startswith("/api/excel2csv/download/"):
            return self._serve_excel_csv(path)
        if path.startswith("/api/excel2csv/zip/"):
            return self._serve_excel_zip(path)
        if path.startswith("/api/excel2json/download/"):
            return self._serve_excel_json(path)
        if path.startswith("/api/excel2json/zip/"):
            return self._serve_excel_json_zip(path)
        if path in ("/", "/index.html"):
            path = "/index.html"
        target = STATIC_DIR / path.lstrip("/")
        if not target.is_file():
            return self._send_json({"error": "not found"}, 404)
        ext = target.suffix.lower()
        return self._send_bytes(target.read_bytes(), MIME.get(ext, "application/octet-stream"))

    def _serve_asset(self, path):
        parts = path[len("/api/assets/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad asset path"}, 400)
        token, name = parts
        job = _JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        asset_path = job["assets_dir"] / name
        if not asset_path.is_file():
            return self._send_json({"error": "not found"}, 404)
        ext = asset_path.suffix.lower()
        return self._send_bytes(asset_path.read_bytes(), MIME.get(ext, "application/octet-stream"))

    def _serve_download(self, path):
        token = path[len("/api/download/"):].strip("/")
        job = _JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(job["md_path"], job["stem"] + ".md")
            if job["assets_dir"].is_dir():
                for file_path in sorted(job["assets_dir"].iterdir()):
                    archive.write(file_path, job["assets_dir"].name + "/" + file_path.name)
        data = buffer.getvalue()
        return self._send_bytes(
            data,
            "application/zip",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"download.zip\"; filename*=UTF-8''{0}".format(
                    quote(job["stem"] + ".zip")
                )
            },
        )

    def _serve_pdf_image(self, path):
        parts = path[len("/api/pdf2image/files/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad image path"}, 400)
        token, name = parts
        job = _PDF_IMAGE_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        image_path = job["images_dir"] / name
        if not image_path.is_file():
            return self._send_json({"error": "not found"}, 404)
        ext = image_path.suffix.lower()
        return self._send_bytes(image_path.read_bytes(), MIME.get(ext, "application/octet-stream"))

    def _serve_pdf_images_zip(self, path):
        token = path[len("/api/pdf2image/download/"):].strip("/")
        job = _PDF_IMAGE_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for image_path in sorted(job["images_dir"].iterdir()):
                archive.write(image_path, image_path.name)
        data = buffer.getvalue()
        return self._send_bytes(
            data,
            "application/zip",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"pdf-images.zip\"; filename*=UTF-8''{0}".format(
                    quote(job["stem"] + "-images.zip")
                )
            },
        )

    def _serve_pdf_word(self, path):
        token = path[len("/api/pdf2word/download/"):].strip("/")
        job = _PDF_WORD_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        data = job["docx_path"].read_bytes()
        output_name = job.get("output_name") or (job["stem"] + ".docx")
        return self._send_bytes(
            data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"converted.docx\"; filename*=UTF-8''{0}".format(
                    quote(output_name)
                )
            },
        )

    def _serve_excel_csv(self, path):
        parts = path[len("/api/excel2csv/download/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad csv path"}, 400)
        token, index_text = parts
        job = _EXCEL_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        try:
            index = int(index_text)
        except ValueError:
            return self._send_json({"error": "bad sheet index"}, 400)
        sheet = job["sheets"][index]
        data = sheet["csv_path"].read_bytes()
        output_name = sheet["name"] + ".csv"
        return self._send_bytes(
            data,
            "text/csv; charset=utf-8",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"sheet.csv\"; filename*=UTF-8''{0}".format(
                    quote(output_name)
                )
            },
        )

    def _serve_excel_zip(self, path):
        token = path[len("/api/excel2csv/zip/"):].strip("/")
        job = _EXCEL_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        data = job["zip_path"].read_bytes()
        return self._send_bytes(
            data,
            "application/zip",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"excel-csv.zip\"; filename*=UTF-8''{0}".format(
                    quote(job["stem"] + "-csv.zip")
                )
            },
        )

    def _serve_excel_json(self, path):
        parts = path[len("/api/excel2json/download/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad json path"}, 400)
        token, index_text = parts
        job = _EXCEL_JSON_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        try:
            index = int(index_text)
        except ValueError:
            return self._send_json({"error": "bad sheet index"}, 400)
        sheet = job["sheets"][index]
        data = sheet["json_path"].read_bytes()
        output_name = sheet["name"] + ".json"
        return self._send_bytes(
            data,
            "application/json; charset=utf-8",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"sheet.json\"; filename*=UTF-8''{0}".format(
                    quote(output_name)
                )
            },
        )

    def _serve_excel_json_zip(self, path):
        token = path[len("/api/excel2json/zip/"):].strip("/")
        job = _EXCEL_JSON_JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        data = job["zip_path"].read_bytes()
        return self._send_bytes(
            data,
            "application/zip",
            extra_headers={
                "Content-Disposition": "attachment; filename=\"excel-json.zip\"; filename*=UTF-8''{0}".format(
                    quote(job["stem"] + "-json.zip")
                )
            },
        )

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/pdf2image/convert":
            return self._convert_pdf_to_images(parsed)
        if parsed.path == "/api/pdf2word/convert":
            return self._convert_pdf_to_word(parsed)
        if parsed.path == "/api/excel2csv/convert":
            return self._convert_excel_to_csvs(parsed)
        if parsed.path == "/api/excel2json/convert":
            return self._convert_excel_to_json(parsed)
        if parsed.path != "/api/convert":
            return self._send_json({"error": "not found"}, 404)

        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.docx"])[0]
        styles = (query.get("styles") or ["drop"])[0]
        if styles not in ("html", "drop"):
            styles = "drop"
        assets = (query.get("assets") or ["folder"])[0]
        if assets not in ("folder", "base64", "placeholder"):
            assets = "folder"

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return self._send_json({"error": "请求体为空"}, 400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)

            stem = _safe_stem(Path(filename).stem)
            token = uuid.uuid4().hex
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_out" / token
            report, md_path = convert(
                tmp_path,
                out_dir,
                config=Config(inline_style=styles, assets_mode=assets),
                basename=stem,
            )
            if md_path is None:
                return self._send_json({"error": "转换失败", "report": report.to_dict()}, 422)

            report.source = filename
            markdown = md_path.read_text(encoding="utf-8")

            assets_dir = out_dir / (stem + ".assets")
            images = []
            if assets_dir.is_dir():
                for asset in sorted(assets_dir.iterdir()):
                    if asset.is_file():
                        images.append(
                            {
                                "path": stem + ".assets/" + asset.name,
                                "url": "/api/assets/{0}/{1}".format(token, asset.name),
                                "size": asset.stat().st_size,
                            }
                        )
            _JOBS[token] = {"md_path": md_path, "assets_dir": assets_dir, "stem": stem}

            return self._send_json(
                {
                    "filename": filename,
                    "markdown": markdown,
                    "report": report.to_dict(),
                    "images": images,
                    "download_url": "/api/download/{0}".format(token) if images else None,
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _convert_pdf_to_images(self, parsed):
        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.pdf"])[0]
        image_format = (query.get("format") or ["png"])[0]
        if image_format not in ("png", "jpg", "jpeg"):
            image_format = "png"

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return self._send_json({"error": "请求体为空"}, 400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)

            stem = _safe_stem(Path(filename).stem)
            token = uuid.uuid4().hex
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_pdfimg" / token
            image_paths = convert_pdf_to_images(tmp_path, out_dir, image_format=image_format)

            _PDF_IMAGE_JOBS[token] = {"images_dir": out_dir, "stem": stem}
            images = []
            for index, image_path in enumerate(image_paths, start=1):
                images.append(
                    {
                        "name": image_path.name,
                        "url": "/api/pdf2image/files/{0}/{1}".format(token, image_path.name),
                        "size": image_path.stat().st_size,
                    }
                )

            return self._send_json(
                {
                    "filename": filename,
                    "page_count": len(images),
                    "images": images,
                    "download_url": "/api/pdf2image/download/{0}".format(token),
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _convert_pdf_to_word(self, parsed):
        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.pdf"])[0]

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return self._send_json({"error": "请求体为空"}, 400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)

            stem = _safe_stem(Path(filename).stem)
            output_name = Path(filename).stem + ".docx"
            token = uuid.uuid4().hex
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_pdfword" / token
            out_dir.mkdir(parents=True, exist_ok=True)
            docx_path = out_dir / (stem + ".docx")
            convert_pdf_to_word(tmp_path, docx_path)

            preview_dir = out_dir / "preview"
            report, md_path = convert(
                docx_path,
                preview_dir,
                config=Config(inline_style="drop", assets_mode="placeholder"),
                basename="preview",
            )
            preview_markdown = md_path.read_text(encoding="utf-8") if md_path else ""

            _PDF_WORD_JOBS[token] = {"docx_path": docx_path, "stem": stem, "output_name": output_name}
            return self._send_json(
                {
                    "filename": filename,
                    "output_name": output_name,
                    "preview_markdown": preview_markdown,
                    "download_url": "/api/pdf2word/download/{0}".format(token),
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _convert_excel_to_csvs(self, parsed):
        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.xlsx"])[0]

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return self._send_json({"error": "请求体为空"}, 400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)

            stem = _safe_stem(Path(filename).stem)
            token = uuid.uuid4().hex
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_excel" / token
            sheets, zip_path = convert_excel_to_csvs(tmp_path, out_dir)

            _EXCEL_JOBS[token] = {"sheets": sheets, "zip_path": zip_path, "stem": stem}
            sheet_data = []
            for index, sheet in enumerate(sheets):
                sheet_data.append(
                    {
                        "name": sheet["name"],
                        "total_rows": sheet["total_rows"],
                        "columns": sheet["columns"],
                        "preview": sheet["preview"],
                        "csv_url": "/api/excel2csv/download/{0}/{1}".format(token, index),
                    }
                )
            return self._send_json(
                {
                    "filename": filename,
                    "sheets": sheet_data,
                    "zip_url": "/api/excel2csv/zip/{0}".format(token),
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _convert_excel_to_json(self, parsed):
        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.xlsx"])[0]
        mode = (query.get("mode") or ["standard"])[0]
        if mode not in ("standard", "wechat"):
            mode = "standard"

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if not body:
            return self._send_json({"error": "请求体为空"}, 400)

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(body)
                tmp_path = Path(tmp.name)

            stem = _safe_stem(Path(filename).stem)
            token = uuid.uuid4().hex
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_exceljson" / token
            sheets, zip_path = convert_excel_to_json(tmp_path, out_dir, mode=mode)

            _EXCEL_JSON_JOBS[token] = {"sheets": sheets, "zip_path": zip_path, "stem": stem}
            sheet_data = []
            for index, sheet in enumerate(sheets):
                sheet_data.append(
                    {
                        "name": sheet["name"],
                        "total_rows": sheet["total_rows"],
                        "columns": sheet["columns"],
                        "preview": sheet["preview"],
                        "json_url": "/api/excel2json/download/{0}/{1}".format(token, index),
                    }
                )
            return self._send_json(
                {
                    "filename": filename,
                    "mode": mode,
                    "sheets": sheet_data,
                    "zip_url": "/api/excel2json/zip/{0}".format(token),
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def log_message(self, fmt, *args):
        return


def _safe_stem(name):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return cleaned.strip("._") or "document"


def main(host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), Handler)
    print("QuickTransform is running at http://{0}:{1}".format(host, port))
    server.serve_forever()


if __name__ == "__main__":
    main()
