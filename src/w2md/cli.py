"""Command line entry point."""

import argparse
import json
from pathlib import Path

from .config import Config
from .pipeline import convert
from .placeholder_replace import (
    analyze_replacement,
    replace_placeholders,
    update_manifest,
)


def build_parser():
    parser = argparse.ArgumentParser(prog="w2md", description="Word (.docx) to Markdown converter")
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="convert .docx files to Markdown")
    conv.add_argument("inputs", nargs="+", help="input .docx files or directories")
    conv.add_argument("-o", "--output", required=True, help="output directory")
    conv.add_argument(
        "--heading-offset",
        type=int,
        default=1,
        help="shift all heading levels (default: 1, Word H1 -> Markdown ##)",
    )
    conv.add_argument("--styles", choices=["drop", "html"], default="drop", help="inline style handling (default: drop)")
    conv.add_argument("--assets", choices=["folder", "base64", "placeholder"], default="folder", help="image handling (default: folder)")
    conv.add_argument("--no-image-previews", action="store_true", help="disable conversion/preview generation for EMF/WMF/TIFF and oversized images")
    conv.add_argument("--max-upload-mb", type=float, default=5.0, help="upload copy size limit in MB (default: 5)")
    conv.add_argument("--max-image-dimension", type=int, default=4000, help="max width/height before an image is treated as oversized (default: 4000)")
    conv.add_argument("--preview-max-dimension", type=int, default=2000, help="max dimension for oversized preview upload copies (default: 2000)")

    images = sub.add_parser(
        "extract-images",
        help="extract DOCX images in body order and generate ShowDoc placeholders",
    )
    images.add_argument("inputs", nargs="+", help="input .docx files or directories")
    images.add_argument("-o", "--output", required=True, help="output directory")
    images.add_argument("--heading-offset", type=int, default=1)
    images.add_argument("--styles", choices=["drop", "html"], default="drop", help="inline style handling (default: drop)")
    images.add_argument("--no-image-previews", action="store_true", help="disable conversion/preview generation for EMF/WMF/TIFF and oversized images")
    images.add_argument("--max-upload-mb", type=float, default=5.0, help="upload copy size limit in MB (default: 5)")
    images.add_argument("--max-image-dimension", type=int, default=4000, help="max width/height before an image is treated as oversized (default: 4000)")
    images.add_argument("--preview-max-dimension", type=int, default=2000, help="max dimension for oversized preview upload copies (default: 2000)")

    replace = sub.add_parser(
        "replace-placeholders",
        help="fill ShowDoc image URLs back into Markdown placeholders (legacy order mode)",
    )
    replace.add_argument("markdown", help="Markdown file containing placeholders")
    replace.add_argument("--showdoc", required=True, help="ShowDoc Markdown source file")
    replace.add_argument("-o", "--output", required=True, help="output directory")
    replace.add_argument("--manifest", help="optional manifest.json from image extraction")
    replace.add_argument("--mapping", help="optional JSON mapping: [{placeholder, url}]")

    upload = sub.add_parser(
        "apply-upload-result",
        help="import browser extension upload_result.json and replace only successful images",
    )
    upload.add_argument("markdown", help="Markdown file containing {{SHOWDOC_IMAGE_...}} placeholders")
    upload.add_argument(
        "--upload-result",
        required=True,
        help="upload_result.json exported by the ShowDoc upload recorder extension",
    )
    upload.add_argument("--manifest", help="manifest.json from image extraction (recommended)")
    upload.add_argument("-o", "--output", required=True, help="output directory")
    upload.add_argument(
        "--mode",
        choices=["partial", "strict", "fill-remaining"],
        default="partial",
        help="partial = replace successes and keep failures (default); "
        "strict = require every expected image; fill-remaining = only touch placeholders still in the Markdown",
    )
    upload.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="continue when document_id / placeholder / SHA-256 disagree (mismatching images stay as placeholders)",
    )
    upload.add_argument(
        "--confirm-partial",
        action="store_true",
        help="confirm generating with missing images in partial mode",
    )
    upload.add_argument(
        "--assets-dir",
        help="optional image directory; missing_images.html embeds thumbnails from here",
    )
    upload.add_argument(
        "--no-html",
        action="store_true",
        help="do not write the optional missing_images.html",
    )

    serve = sub.add_parser("serve", help="start the local web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in ("convert", "extract-images"):
        assets_mode = "placeholder" if args.command == "extract-images" else args.assets
        config = Config(
            heading_offset=args.heading_offset,
            inline_style=args.styles,
            assets_mode=assets_mode,
            image_previews=not args.no_image_previews,
            max_upload_bytes=max(1, int(args.max_upload_mb * 1024 * 1024)),
            max_image_dimension=max(1, args.max_image_dimension),
            preview_max_dimension=max(1, args.preview_max_dimension),
        )
        output = Path(args.output)
        for raw in args.inputs:
            path = Path(raw)
            files = sorted(path.glob("*.docx")) if path.is_dir() else [path]
            for file_path in files:
                report, md_path = convert(file_path, output, config)
                if md_path:
                    print("[{0}] {1} -> {2}".format(report.status, file_path.name, md_path))
                    if args.command == "extract-images":
                        stats = report.stats
                        print(
                            "  images: {0} occurrences, {1} unique, {2} duplicate".format(
                                stats.get("image_occurrences", 0),
                                stats.get("image_unique_media", 0),
                                stats.get("image_duplicates", 0),
                            )
                        )
                        print(
                            "  compatibility: supported {0}, converted {1}, oversized {2}, "
                            "conversion_failed {3}, unsupported {4}, special {5}".format(
                                stats.get("image_supported", 0),
                                stats.get("image_converted", 0),
                                stats.get("image_oversized", 0),
                                stats.get("image_conversion_failed", 0),
                                stats.get("image_unsupported", 0),
                                stats.get("image_special", 0),
                            )
                        )
                        print("  assets: {0}".format(output / "assets"))
                        print("  manifest: {0}".format(output / "assets" / "manifest.json"))
                    for warning in report.warnings:
                        print("  {0}: {1}: {2}".format(warning.level, warning.kind, warning.detail))
                else:
                    print("[error] {0} conversion failed".format(file_path.name))
    elif args.command == "replace-placeholders":
        return _run_replace(args)
    elif args.command == "apply-upload-result":
        return _run_apply_upload_result(args)
    elif args.command == "serve":
        from .server.app import main as serve_main

        serve_main(host=args.host, port=args.port)

    return 0


def _run_replace(args):
    markdown_path = Path(args.markdown)
    showdoc_path = Path(args.showdoc)
    if not markdown_path.is_file():
        print("[error] Markdown 文件不存在: {0}".format(markdown_path))
        return 1
    if not showdoc_path.is_file():
        print("[error] ShowDoc Markdown 文件不存在: {0}".format(showdoc_path))
        return 1

    markdown = markdown_path.read_text(encoding="utf-8")
    showdoc = showdoc_path.read_text(encoding="utf-8")
    manifest = None
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    mapping = None
    if args.mapping:
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))

    analysis = analyze_replacement(markdown, showdoc, manifest=manifest, mapping=mapping)
    if not analysis.can_generate:
        print("[error] 校验未通过，未生成最终 Markdown")
        for error in analysis.errors:
            print("  - {0}".format(error))
        for warning in analysis.warnings:
            print("  ! {0}".format(warning))
        return 1

    mapping_dict = {
        item.placeholder: item.url for item in analysis.mapping if item.url
    }
    alt = {item.placeholder: item.alt_text for item in analysis.mapping}
    result = replace_placeholders(markdown, mapping_dict, alt, analysis)
    if result.errors:
        print("[error] 替换失败")
        for error in result.errors:
            print("  - {0}".format(error))
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = markdown_path.stem
    md_path = output_dir / (stem + ".replaced.md")
    md_path.write_text(result.markdown, encoding="utf-8")

    manifest_path = None
    if manifest is not None:
        manifest_path = output_dir / (stem + ".manifest.replaced.json")
        manifest_path.write_text(
            json.dumps(update_manifest(manifest, mapping_dict), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    report = {
        "source": str(markdown_path),
        "showdoc_source": str(showdoc_path),
        "analysis": analysis.to_dict(),
        "replacement": {
            "replaced_count": result.replaced_count,
            "skipped_code_count": result.skipped_code_count,
            "errors": result.errors,
            "warnings": result.warnings,
        },
    }
    report_path = output_dir / (stem + ".replace.report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("[ok] {0} -> {1}".format(markdown_path.name, md_path))
    print("  replaced: {0}".format(result.replaced_count))
    print("  skipped in code: {0}".format(result.skipped_code_count))
    if manifest_path is not None:
        print("  manifest: {0}".format(manifest_path))
    print("  report: {0}".format(report_path))
    for warning in analysis.warnings + result.warnings:
        print("  ! {0}".format(warning))
    return 0


def _run_apply_upload_result(args):
    from .upload_result import (
        analyze_upload_result,
        apply_analysis,
        thumbnails_from_files,
        write_outputs,
    )

    markdown_path = Path(args.markdown)
    upload_path = Path(args.upload_result)
    if not markdown_path.is_file():
        print("[error] Markdown 文件不存在: {0}".format(markdown_path))
        return 1
    if not upload_path.is_file():
        print("[error] upload_result.json 不存在: {0}".format(upload_path))
        return 1

    manifest = None
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_file():
            print("[error] manifest.json 不存在: {0}".format(manifest_path))
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    try:
        upload_result = json.loads(upload_path.read_text(encoding="utf-8"))
    except ValueError as error:
        print("[error] upload_result.json 解析失败: {0}".format(error))
        return 1

    markdown = markdown_path.read_text(encoding="utf-8")
    mode = {
        "partial": "partial",
        "strict": "strict",
        "fill-remaining": "fill_remaining",
    }[args.mode]
    analysis = analyze_upload_result(
        markdown,
        upload_result,
        manifest=manifest,
        mode=mode,
        allow_mismatch=args.allow_mismatch,
    )

    counts = analysis.counts
    print(
        "图片: manifest {0} / 普通 {1} / 特殊 {2} / Markdown 普通占位符 {3} / "
        "Markdown 特殊占位符 {4}".format(
            counts.get("manifest_images", 0),
            counts.get("normal_images", 0),
            counts.get("special_images", 0),
            counts.get("markdown_normal_placeholders", 0),
            counts.get("markdown_special_placeholders", 0),
        )
    )
    print(
        "上传: 成功 {0} / 失败 {1} / 未上传 {2} / 待定或中断 {3} / 无法匹配 {4} / 意外上传 {5}".format(
            counts.get("success", 0),
            counts.get("failed", 0),
            counts.get("not_uploaded", 0),
            counts.get("pending", 0) + counts.get("interrupted", 0),
            counts.get("unmatched", 0),
            counts.get("unexpected_upload", 0),
        )
    )
    print(
        "兼容性: supported {0} / converted {1} / oversized {2} / "
        "conversion_failed {3} / unsupported {4}".format(
            counts.get("supported", 0),
            counts.get("converted", 0),
            counts.get("oversized", 0),
            counts.get("conversion_failed", 0),
            counts.get("unsupported", 0),
        )
    )

    for warning in analysis.warnings:
        print("  ! {0}".format(warning))
    for error in analysis.errors:
        print("  - {0}".format(error))

    if not analysis.can_generate:
        print("[error] 校验未通过，未生成最终 Markdown")
        return 1

    if analysis.requires_confirmation and not args.confirm_partial:
        print(
            "[stop] 生成前仍有需要确认的差异（失败 {0}、未上传 {1}、待定/中断 {2}、"
            "无法匹配 {3}、统计差异 {4} 项）。确认要生成时请加 --confirm-partial。".format(
                counts.get("failed", 0),
                counts.get("not_uploaded", 0),
                counts.get("pending", 0) + counts.get("interrupted", 0),
                counts.get("unmatched", 0),
                len(analysis.declared_differences),
            )
        )
        return 2

    outcome = apply_analysis(markdown, analysis)
    for warning in outcome.warnings:
        print("  ! {0}".format(warning))
    for error in outcome.post_errors:
        print("  - {0}".format(error))

    thumbnail_roots = []
    if args.assets_dir:
        thumbnail_roots.append(Path(args.assets_dir))
    if args.manifest:
        manifest_dir = Path(args.manifest).resolve().parent
        thumbnail_roots.extend([manifest_dir, manifest_dir.parent])
    thumbnails = (
        {}
        if args.no_html
        else thumbnails_from_files(analysis, thumbnail_roots)
    )

    paths = write_outputs(
        Path(args.output),
        outcome.markdown,
        analysis,
        outcome,
        inputs={
            "markdown": str(markdown_path),
            "upload_result": str(upload_path),
            "manifest": str(args.manifest) if args.manifest else None,
        },
        thumbnails=thumbnails,
        include_html=not args.no_html,
    )

    print("[ok] replaced {0}, remaining placeholders {1}".format(
        outcome.replaced_count,
        len(outcome.remaining_placeholders),
    ))
    print("  markdown: {0}".format(paths["markdown"]))
    print("  missing csv: {0}".format(paths["csv"]))
    print("  report: {0}".format(paths["report"]))
    if paths["html"] is not None:
        print("  missing html: {0}".format(paths["html"]))
    return 0 if outcome.ok else 1
