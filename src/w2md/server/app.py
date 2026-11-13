"""Stdlib-only local web server for the converter UI."""

import io
import json
import tempfile
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from ..config import Config
from ..excel2csv import convert_excel_to_csvs
from ..excel2json import convert_excel_to_json
from ..image_extract import extract_images_from_package
from ..opc.package import OpcPackage
from ..pdf_to_images import convert_pdf_to_images
from ..pdf_to_word import convert_pdf_to_word
from ..pipeline import convert
from ..placeholder_replace import (
    analyze_replacement,
    replace_placeholders,
    update_manifest,
)


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
    ".emf": "image/emf",
    ".wmf": "image/wmf",
    ".json": "application/json; charset=utf-8",
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
        headers = dict(extra_headers or {})
        start = getattr(self, "_request_start", None)
        if start is not None:
            headers.setdefault(
                "X-Process-Time", "{0:.3f}s".format(time.perf_counter() - start)
            )
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for key, value in headers.items():
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
            return self._serve_asset(path, parsed.query)
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

    def _serve_asset(self, path, query=""):
        parts = path[len("/api/assets/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad asset path"}, 400)
        token, name = parts
        name = unquote(name)
        job = _JOBS.get(token)
        if not job:
            return self._send_json({"error": "not found"}, 404)
        base_dir = Path(job["assets_dir"]).resolve()
        asset_path = (base_dir / name).resolve()
        if asset_path != base_dir and base_dir not in asset_path.parents:
            return self._send_json({"error": "not found"}, 404)
        if not asset_path.is_file():
            return self._send_json({"error": "not found"}, 404)
        ext = asset_path.suffix.lower()
        headers = {}
        if parse_qs(query).get("download"):
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''{0}".format(
                quote(asset_path.name)
            )
        return self._send_bytes(
            asset_path.read_bytes(),
            MIME.get(ext, "application/octet-stream"),
            extra_headers=headers,
        )

    def _serve_download(self, path):
        token = path[len("/api/download/"):].strip("/")
        job = _JOBS.get(token)
        if not job or not job.get("md_path"):
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
        self._request_start = time.perf_counter()
        parsed = urlparse(self.path)
        if parsed.path == "/api/pdf2image/convert":
            return self._convert_pdf_to_images(parsed)
        if parsed.path == "/api/pdf2word/convert":
            return self._convert_pdf_to_word(parsed)
        if parsed.path == "/api/excel2csv/convert":
            return self._convert_excel_to_csvs(parsed)
        if parsed.path == "/api/excel2json/convert":
            return self._convert_excel_to_json(parsed)
        if parsed.path == "/api/word2image/extract":
            return self._extract_word_images(parsed)
        if parsed.path == "/api/word2image/zip":
            return self._zip_word_images()
        if parsed.path == "/api/placeholder-replace/analyze":
            return self._analyze_placeholder_replace()
        if parsed.path == "/api/placeholder-replace/generate":
            return self._generate_placeholder_replace()
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

            manifest = None
            manifest_url = None
            if assets == "placeholder":
                assets_dir = out_dir / "assets"
                manifest_path = assets_dir / "manifest.json"
                if manifest_path.is_file():
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest_url = "/api/assets/{0}/manifest.json".format(token)
                images = []
                for entry in (manifest or {}).get("images", []):
                    local_path = entry.get("local_path")
                    if not local_path:
                        continue
                    file_name = Path(local_path).name
                    file_path = assets_dir / file_name
                    if not file_path.is_file():
                        continue
                    images.append(
                        {
                            "path": local_path,
                            "url": "/api/assets/{0}/{1}".format(token, file_name),
                            "size": file_path.stat().st_size,
                            "placeholder": entry.get("placeholder"),
                            "alt": entry.get("alt_text"),
                        }
                    )
            else:
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
                    "manifest": manifest,
                    "manifest_url": manifest_url,
                    "download_url": "/api/download/{0}".format(token)
                    if images or manifest
                    else None,
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def _analyze_placeholder_replace(self):
        payload = self._read_json_body()
        if payload is None:
            return self._send_json({"error": "请求格式错误"}, 400)
        analysis = analyze_replacement(
            payload.get("markdown") or "",
            payload.get("showdoc_markdown") or "",
            manifest=payload.get("manifest"),
            mapping=payload.get("mapping"),
        )
        return self._send_json(analysis.to_dict())

    def _generate_placeholder_replace(self):
        payload = self._read_json_body()
        if payload is None:
            return self._send_json({"error": "请求格式错误"}, 400)

        markdown = payload.get("markdown") or ""
        showdoc = payload.get("showdoc_markdown") or ""
        manifest = payload.get("manifest")
        analysis = analyze_replacement(
            markdown,
            showdoc,
            manifest=manifest,
            mapping=payload.get("mapping"),
        )
        if not analysis.can_generate:
            data = analysis.to_dict()
            data["error"] = "校验未通过，未生成最终 Markdown"
            return self._send_json(data, 422)

        mapping = {
            item.placeholder: item.url for item in analysis.mapping if item.url
        }
        alt = {item.placeholder: item.alt_text for item in analysis.mapping}
        result = replace_placeholders(markdown, mapping, alt, analysis)
        if result.errors:
            data = analysis.to_dict()
            data.update(result.to_dict())
            data["error"] = "替换失败，未生成最终 Markdown"
            return self._send_json(data, 422)

        return self._send_json(
            {
                "analysis": analysis.to_dict(),
                "markdown": result.markdown,
                "replaced_count": result.replaced_count,
                "skipped_code_count": result.skipped_code_count,
                "warnings": result.warnings,
                "updated_manifest": update_manifest(manifest, mapping),
            }
        )

    def _extract_word_images(self, parsed):
        query = parse_qs(parsed.query)
        filename = (query.get("filename") or ["upload.docx"])[0]
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
            out_dir = Path(tempfile.gettempdir()) / "quicktranser_word_images" / token

            with OpcPackage(tmp_path) as package:
                result = extract_images_from_package(package, out_dir, stem=stem)

            images = []
            for occurrence in result.occurrences:
                image = {
                    "placeholder": occurrence.placeholder,
                    "order": occurrence.order,
                    "relationship_id": occurrence.relationship_id,
                    "source_part": occurrence.source_part,
                    "filename": Path(occurrence.local_path).name if occurrence.local_path else None,
                    "url": None,
                    "size": occurrence.size,
                    "mime_type": occurrence.mime_type,
                    "extension": occurrence.extension,
                    "sha256": occurrence.sha256,
                    "sha256_verified": occurrence.sha256_verified,
                    "alt_text": occurrence.alt_text,
                    "alt_source": occurrence.alt_source,
                    "is_duplicate": occurrence.is_duplicate,
                    "duplicate_of": occurrence.duplicate_of,
                    "is_compatibility_format": occurrence.is_compatibility_format,
                    "preview_url": None,
                    "preview_status": occurrence.preview_status,
                    "status": occurrence.status,
                    "error": occurrence.error,
                }
                if occurrence.local_path:
                    image["url"] = "/api/assets/{0}/{1}".format(
                        token, Path(occurrence.local_path).name
                    )
                if occurrence.preview_path:
                    image["preview_url"] = "/api/assets/{0}/{1}".format(
                        token, Path(occurrence.preview_path).name
                    )
                images.append(image)

            _JOBS[token] = {"assets_dir": result.assets_dir, "stem": stem, "md_path": None}
            return self._send_json(
                {
                    "filename": filename,
                    "token": token,
                    "images": images,
                    "summary": result.summary,
                    "manifest_url": "/api/assets/{0}/manifest.json".format(token),
                    "notes": result.notes,
                    "errors": result.errors,
                }
            )
        except Exception as exc:
            return self._send_json({"error": str(exc)}, 500)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    def _zip_word_images(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return self._send_json({"error": "请求格式错误"}, 400)

        token = payload.get("token")
        names = payload.get("files") or []
        job = _JOBS.get(token)
        if not job or not job.get("assets_dir"):
            return self._send_json({"error": "任务已过期，请重新提取"}, 404)

        base_dir = Path(job["assets_dir"]).resolve()
        buffer = io.BytesIO()
        added = 0
        seen = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for raw_name in names:
                name = Path(str(raw_name)).name
                if not name or name in seen:
                    continue
                asset_path = (base_dir / name).resolve()
                if base_dir not in asset_path.parents or not asset_path.is_file():
                    continue
                archive.write(asset_path, arcname=name)
                seen.add(name)
                added += 1

        if not added:
            return self._send_json({"error": "没有可打包的图片"}, 400)

        zip_name = Path(str(payload.get("zip_name") or "word-images.zip")).name
        return self._send_bytes(
            buffer.getvalue(),
            "application/zip",
            extra_headers={
                "Content-Disposition": "attachment; filename*=UTF-8''{0}".format(quote(zip_name))
            },
        )

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
