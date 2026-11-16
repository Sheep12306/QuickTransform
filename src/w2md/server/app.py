"""Stdlib-only local web server for the converter UI."""

import io
import json
import re
import shutil
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
from ..special_images import (
    analyze_special_images,
    apply_special_images,
    update_special_manifest,
)
from ..upload_result import (
    analyze_upload_result,
    apply_analysis as apply_upload_analysis,
    build_missing_rows,
    missing_images_csv,
    missing_images_html,
    output_names,
    replacement_report,
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
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
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
_WORD2IMAGE_ZIPS = {}
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
        if path.startswith("/api/word2image/zip-download/"):
            return self._serve_word_zip(path)
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

    def _recover_asset_job(self, token):
        if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
            return None
        roots = [
            Path(tempfile.gettempdir()) / "quicktranser_out",
            Path(tempfile.gettempdir()) / "quicktranser_word_images",
            Path(tempfile.gettempdir()) / "quicktranser_pdfword",
            Path(tempfile.gettempdir()) / "quicktranser_pdfimage",
            Path(tempfile.gettempdir()) / "quicktranser_excel",
            Path(tempfile.gettempdir()) / "quicktranser_excel_json",
        ]
        for root in roots:
            base = root / token
            if not base.is_dir():
                continue
            for assets in list(base.glob("assets")) + list(base.glob("*.assets")):
                if assets.is_dir():
                    return {"assets_dir": assets, "stem": token, "md_path": None}
            for assets in base.rglob("assets"):
                if assets.is_dir():
                    return {"assets_dir": assets, "stem": token, "md_path": None}
        return None

    def _serve_asset(self, path, query=""):
        parts = path[len("/api/assets/"):].split("/", 1)
        if len(parts) != 2:
            return self._send_json({"error": "bad asset path"}, 400)
        token, name = parts
        name = _asset_relative(unquote(name))
        job = _JOBS.get(token)
        if not job:
            job = self._recover_asset_job(token)
            if job:
                _JOBS[token] = job
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
                for file_path in sorted(job["assets_dir"].rglob("*")):
                    if not file_path.is_file():
                        continue
                    relative = file_path.relative_to(job["assets_dir"]).as_posix()
                    archive.write(
                        file_path,
                        job["assets_dir"].name + "/" + relative,
                    )
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
        if parsed.path == "/api/special-images/analyze":
            return self._analyze_special_images()
        if parsed.path == "/api/special-images/generate":
            return self._generate_special_images()
        if parsed.path == "/api/upload-result/analyze":
            return self._analyze_upload_result()
        if parsed.path == "/api/upload-result/generate":
            return self._generate_upload_result()
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
                source_name=filename,
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
                    relative = _asset_relative(local_path)
                    file_path = assets_dir / relative
                    if not file_path.is_file():
                        continue
                    source_path = entry.get("source_file")
                    upload_path = entry.get("upload_file")
                    image = {
                        "sequence": entry.get("sequence"),
                        "occurrence_id": entry.get("occurrence_id"),
                        "path": local_path,
                        "url": "/api/assets/{0}/{1}".format(token, quote(relative)),
                        "size": entry.get("size") or file_path.stat().st_size,
                        "placeholder": entry.get("placeholder"),
                        "alt": entry.get("alt_text"),
                        "compatibility": entry.get("compatibility"),
                        "source_path": source_path,
                        "upload_path": upload_path,
                        "source_filename": Path(str(source_path)).name if source_path else None,
                        "upload_filename": Path(str(upload_path)).name if upload_path else None,
                        "source_url": (
                            "/api/assets/{0}/{1}".format(
                                token, quote(_asset_relative(source_path))
                            )
                            if source_path
                            else None
                        ),
                        "upload_url": (
                            "/api/assets/{0}/{1}".format(
                                token, quote(_asset_relative(upload_path))
                            )
                            if upload_path
                            else None
                        ),
                    }
                    images.append(image)
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

    def _special_images_payload(self):
        payload = self._read_json_body()
        if payload is None:
            return None, {"error": "请求格式错误"}
        if not str(payload.get("markdown") or "").strip():
            return None, {"error": "缺少 Markdown 源码"}
        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            return None, {"error": "缺少 manifest.json。请选择图片提取生成的 manifest。"}
        urls = payload.get("urls")
        if urls is not None and not isinstance(urls, (dict, list)):
            return None, {"error": "URL mapping 格式错误"}
        return payload, None

    def _analyze_special_images(self):
        payload = self._read_json_body()
        if payload is None:
            return self._send_json({"error": "请求格式错误"}, 400)
        analysis = analyze_special_images(
            payload.get("markdown") or "",
            payload.get("manifest"),
            urls=payload.get("urls"),
        )
        return self._send_json(analysis.to_dict())

    def _generate_special_images(self):
        payload, error = self._special_images_payload()
        if error:
            return self._send_json(error, 400)

        markdown = payload.get("markdown") or ""
        manifest = payload["manifest"]
        analysis = analyze_special_images(markdown, manifest, urls=payload.get("urls"))
        if not analysis.can_generate:
            data = analysis.to_dict()
            data["error"] = "检查未通过，未生成最终 Markdown"
            return self._send_json(data, 422)

        mapping = {
            item.placeholder: item.url
            for item in analysis.items
            if item.status == "matched" and item.url
        }
        alt = {item.placeholder: item.alt_text for item in analysis.items}
        result = apply_special_images(markdown, mapping, alt)
        if result.errors:
            data = analysis.to_dict()
            data.update(result.to_dict())
            data["error"] = "最终占位符残留检查未通过，未生成最终 Markdown"
            return self._send_json(data, 422)

        return self._send_json(
            {
                "analysis": analysis.to_dict(),
                "markdown": result.markdown,
                "replaced_count": result.replaced_count,
                "skipped_code_count": result.skipped_code_count,
                "final_check": result.final_check,
                "warnings": result.warnings,
                "updated_manifest": update_special_manifest(
                    manifest, mapping, analysis=analysis
                ),
            }
        )

    def _upload_payload(self):
        payload = self._read_json_body()
        if payload is None:
            return None, {"error": "请求格式错误"}
        if not isinstance(payload.get("upload_result"), dict):
            return None, {
                "error": "缺少 upload_result.json。请先导出浏览器扩展的上传结果；"
                "没有上传记录时不能生成最终 Markdown。"
            }
        if not str(payload.get("markdown") or "").strip():
            return None, {"error": "缺少带占位符的 Markdown"}
        manifest = payload.get("manifest")
        if manifest is not None and not isinstance(manifest, dict):
            return None, {"error": "manifest.json 格式错误"}
        return payload, None

    def _analyze_upload_result(self):
        payload, error = self._upload_payload()
        if error:
            return self._send_json(error, 400)

        analysis = analyze_upload_result(
            payload.get("markdown") or "",
            payload["upload_result"],
            manifest=payload.get("manifest"),
            mode=payload.get("mode") or "partial",
            allow_mismatch=bool(payload.get("allow_mismatch")),
        )
        return self._send_json(analysis.to_dict())

    def _generate_upload_result(self):
        payload, error = self._upload_payload()
        if error:
            return self._send_json(error, 400)

        analysis = analyze_upload_result(
            payload.get("markdown") or "",
            payload["upload_result"],
            manifest=payload.get("manifest"),
            mode=payload.get("mode") or "partial",
            allow_mismatch=bool(payload.get("allow_mismatch")),
        )
        data = analysis.to_dict()

        if not analysis.can_generate:
            data["error"] = "校验未通过，未生成最终 Markdown"
            return self._send_json(data, 422)

        if analysis.requires_confirmation and not payload.get("confirmed"):
            data["requires_confirmation"] = True
            reasons = []
            if any(
                analysis.counts.get(key, 0)
                for key in (
                    "failed",
                    "not_uploaded",
                    "pending",
                    "interrupted",
                    "unmatched",
                )
            ):
                reasons.append(
                    "失败 {0}、未上传 {1}、待定/中断 {2}、无法匹配 {3}".format(
                        analysis.counts.get("failed", 0),
                        analysis.counts.get("not_uploaded", 0),
                        analysis.counts.get("pending", 0)
                        + analysis.counts.get("interrupted", 0),
                        analysis.counts.get("unmatched", 0),
                    )
                )
            if analysis.declared_differences:
                reasons.append(
                    "upload_result.json 统计差异 {0} 项".format(
                        len(analysis.declared_differences)
                    )
                )
            if analysis.counts.get("manifest_not_in_markdown") or analysis.counts.get(
                "special_not_in_markdown"
            ):
                reasons.append("Markdown 缺少 manifest 占位符")
            if analysis.unknown_placeholders or analysis.unknown_special_placeholders:
                reasons.append("存在 manifest 之外的占位符")
            data["error"] = "生成前仍有需要确认的差异：{0}。请确认后再生成。".format(
                "；".join(reasons) or "部分成功模式"
            )
            return self._send_json(data, 409)

        outcome = apply_upload_analysis(payload.get("markdown") or "", analysis)
        data["analysis"] = analysis.to_dict()
        thumbnails = payload.get("thumbnails")
        if not isinstance(thumbnails, dict):
            thumbnails = {}
        names = output_names()
        missing_rows = build_missing_rows(analysis)
        report = replacement_report(
            analysis,
            outcome,
            inputs={
                "markdown": payload.get("markdown_name") or "",
                "upload_result": payload.get("upload_result_name") or "",
                "manifest": payload.get("manifest_name") or "",
            },
        )

        data.update(
            {
                "markdown": outcome.markdown,
                "replaced_count": outcome.replaced_count,
                "skipped_code_count": outcome.skipped_code_count,
                "skipped_missing_count": outcome.skipped_missing_count,
                "remaining_placeholders": outcome.remaining_placeholders,
                "post_errors": outcome.post_errors,
                "warnings": outcome.warnings,
                "ok": outcome.ok,
                "missing_rows": missing_rows,
                "artifacts": {
                    "markdown": {
                        "filename": names["markdown"],
                        "content": outcome.markdown,
                        "mime": "text/markdown;charset=utf-8",
                    },
                    "csv": {
                        "filename": names["csv"],
                        "content": missing_images_csv(missing_rows),
                        "mime": "text/csv;charset=utf-8",
                    },
                    "report": {
                        "filename": names["report"],
                        "content": json.dumps(report, ensure_ascii=False, indent=2),
                        "mime": "application/json;charset=utf-8",
                    },
                    "html": {
                        "filename": names["html"],
                        "content": missing_images_html(analysis, thumbnails=thumbnails),
                        "mime": "text/html;charset=utf-8",
                    },
                },
                "report": report,
            }
        )
        return self._send_json(data)

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
                result = extract_images_from_package(
                    package,
                    out_dir,
                    stem=stem,
                    source_file=filename,
                    markdown_file=stem + ".md",
                )

            images = []
            for occurrence in result.occurrences:
                source_url = (
                    "/api/assets/{0}/{1}".format(
                        token, quote(_asset_relative(occurrence.source_path))
                    )
                    if occurrence.source_path
                    else None
                )
                upload_url = (
                    "/api/assets/{0}/{1}".format(
                        token, quote(_asset_relative(occurrence.upload_path))
                    )
                    if occurrence.upload_path
                    else None
                )
                image = {
                    "sequence": occurrence.order,
                    "occurrence_id": occurrence.occurrence_id,
                    "placeholder": occurrence.placeholder,
                    "order": occurrence.order,
                    "relationship_id": occurrence.relationship_id,
                    "source_part": occurrence.source_part,
                    "source_path": occurrence.source_path,
                    "upload_path": occurrence.upload_path,
                    "local_path": occurrence.local_path,
                    "source_filename": occurrence.source_file_name,
                    "upload_filename": occurrence.upload_file_name,
                    "filename": occurrence.upload_file_name or occurrence.source_file_name,
                    "file_name": occurrence.file_name,
                    "local_file": occurrence.local_path,
                    "section": occurrence.section,
                    "context_before": occurrence.context_before,
                    "context_after": occurrence.context_after,
                    "source_url": source_url,
                    "upload_url": upload_url,
                    "url": upload_url or source_url,
                    "size": occurrence.size,
                    "source_size": occurrence.source_size,
                    "source_format": occurrence.source_extension.lstrip(".")
                    if occurrence.source_extension
                    else None,
                    "upload_format": occurrence.upload_extension.lstrip(".")
                    if occurrence.upload_extension
                    else None,
                    "mime_type": occurrence.mime_type,
                    "extension": occurrence.extension,
                    "source_sha256": occurrence.source_sha256,
                    "upload_sha256": occurrence.upload_sha256,
                    "sha256": occurrence.sha256,
                    "sha256_verified": occurrence.sha256_verified,
                    "compatibility": occurrence.compatibility,
                    "compatibility_reason": occurrence.compatibility_reason,
                    "requires_conversion": occurrence.requires_conversion,
                    "embedded_part": occurrence.embedded_part,
                    "prog_id": occurrence.prog_id,
                    "embedded_label": occurrence.embedded_label,
                    "manual_upload": occurrence.manual_upload,
                    "source_width": occurrence.source_width,
                    "source_height": occurrence.source_height,
                    "upload_width": occurrence.upload_width,
                    "upload_height": occurrence.upload_height,
                    "alt_text": occurrence.alt_text,
                    "alt_source": occurrence.alt_source,
                    "is_duplicate": occurrence.is_duplicate,
                    "duplicate_of": occurrence.duplicate_of,
                    "is_compatibility_format": occurrence.is_compatibility_format,
                    "preview_url": upload_url if occurrence.preview_path else None,
                    "preview_status": occurrence.preview_status,
                    "status": occurrence.status,
                    "error": occurrence.error,
                }
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

    def _serve_word_zip(self, path):
        token = path.rsplit("/", 1)[-1]
        job = _WORD2IMAGE_ZIPS.pop(token, None)
        if not job:
            return self._send_json({"error": "下载链接已过期，请重新打包"}, 404)
        zip_path = Path(job["path"])
        try:
            if not zip_path.is_file():
                return self._send_json({"error": "打包文件不存在"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(zip_path.stat().st_size))
            self.send_header(
                "Content-Disposition",
                "attachment; filename*=UTF-8''{0}".format(quote(job["name"])),
            )
            self.end_headers()
            with zip_path.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile, 1024 * 1024)
        finally:
            zip_path.unlink(missing_ok=True)

    def _cleanup_word_zips(self):
        cutoff = time.time() - 3600
        for token, job in list(_WORD2IMAGE_ZIPS.items()):
            if job.get("created", 0) >= cutoff:
                continue
            _WORD2IMAGE_ZIPS.pop(token, None)
            try:
                Path(job["path"]).unlink(missing_ok=True)
            except OSError:
                pass

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
        if not job:
            job = self._recover_asset_job(token)
            if job:
                _JOBS[token] = job
        if not job or not job.get("assets_dir"):
            return self._send_json({"error": "任务已过期，请重新提取"}, 404)

        base_dir = Path(job["assets_dir"]).resolve()
        zip_name = Path(str(payload.get("zip_name") or "word-images.zip")).name
        temp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        temp_zip.close()
        zip_path = Path(temp_zip.name)
        added = 0
        seen = set()
        stored = False
        try:
            # Images are already compressed. Storing them verbatim is much
            # faster than deflating hundreds of PNG/JPEG files and also keeps
            # the ZIP bytes identical to the extracted originals.
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as archive:
                for raw_name in names:
                    relative = str(raw_name).replace("\\", "/").strip().lstrip("/")
                    name = Path(relative).name
                    if not name or name in seen:
                        continue
                    candidates = [
                        base_dir / relative,
                        base_dir / "upload" / name,
                        base_dir / "original" / name,
                    ]
                    asset_path = None
                    for candidate in candidates:
                        resolved = candidate.resolve()
                        if (
                            (base_dir == resolved or base_dir in resolved.parents)
                            and resolved.is_file()
                        ):
                            asset_path = resolved
                            break
                    if asset_path is None:
                        continue
                    archive.write(asset_path, arcname=name)
                    seen.add(name)
                    added += 1

            if not added:
                return self._send_json({"error": "没有可打包的图片"}, 400)

            download_token = uuid.uuid4().hex
            _WORD2IMAGE_ZIPS[download_token] = {
                "path": zip_path,
                "name": zip_name,
                "created": time.time(),
            }
            stored = True
            self._cleanup_word_zips()
            return self._send_json(
                {
                    "download_url": "/api/word2image/zip-download/{0}".format(
                        download_token
                    ),
                    "count": added,
                    "size": zip_path.stat().st_size,
                    "zip_name": zip_name,
                }
            )
        finally:
            if not stored:
                zip_path.unlink(missing_ok=True)

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


def _asset_relative(path):
    """Convert a manifest path (``assets/upload/x.png``) to the asset root."""

    text = str(path or "").replace("\\", "/").strip().lstrip("/")
    if text.startswith("assets/"):
        return text[len("assets/"):]
    return text


def _safe_stem(name):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)
    return cleaned.strip("._") or "document"


def main(host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), Handler)
    print("QuickTransform is running at http://{0}:{1}".format(host, port))
    server.serve_forever()


if __name__ == "__main__":
    main()
