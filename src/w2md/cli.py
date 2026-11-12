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
    conv.add_argument("--no-image-previews", action="store_true", help="disable optional PNG previews for EMF/WMF/TIFF")

    images = sub.add_parser(
        "extract-images",
        help="extract DOCX images in body order and generate ShowDoc placeholders",
    )
    images.add_argument("inputs", nargs="+", help="input .docx files or directories")
    images.add_argument("-o", "--output", required=True, help="output directory")
    images.add_argument("--heading-offset", type=int, default=1)
    images.add_argument("--styles", choices=["drop", "html"], default="drop", help="inline style handling (default: drop)")
    images.add_argument("--no-image-previews", action="store_true", help="disable optional PNG previews for EMF/WMF/TIFF")

    replace = sub.add_parser(
        "replace-placeholders",
        help="fill ShowDoc image URLs back into Markdown placeholders",
    )
    replace.add_argument("markdown", help="Markdown file containing placeholders")
    replace.add_argument("--showdoc", required=True, help="ShowDoc Markdown source file")
    replace.add_argument("-o", "--output", required=True, help="output directory")
    replace.add_argument("--manifest", help="optional manifest.json from image extraction")
    replace.add_argument("--mapping", help="optional JSON mapping: [{placeholder, url}]")

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
                            "  images: {0} occurrences, {1} unique, {2} duplicate, {3} failed, "
                            "{4} compatibility".format(
                                stats.get("image_occurrences", 0),
                                stats.get("image_unique_media", 0),
                                stats.get("image_duplicates", 0),
                                stats.get("image_failed", 0),
                                stats.get("image_compatibility", 0),
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
