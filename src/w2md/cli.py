"""Command line entry point."""

import argparse
from pathlib import Path

from .config import Config
from .pipeline import convert


def build_parser():
    parser = argparse.ArgumentParser(prog="w2md", description="Word (.docx) to Markdown converter")
    sub = parser.add_subparsers(dest="command", required=True)

    conv = sub.add_parser("convert", help="convert .docx files to Markdown")
    conv.add_argument("inputs", nargs="+", help="input .docx files or directories")
    conv.add_argument("-o", "--output", required=True, help="output directory")
    conv.add_argument("--heading-offset", type=int, default=0)
    conv.add_argument("--styles", choices=["drop", "html"], default="drop", help="inline style handling (default: drop)")
    conv.add_argument("--assets", choices=["folder", "base64", "placeholder"], default="folder", help="image handling (default: folder)")

    serve = sub.add_parser("serve", help="start the local web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "convert":
        config = Config(heading_offset=args.heading_offset, inline_style=args.styles, assets_mode=args.assets)
        output = Path(args.output)
        for raw in args.inputs:
            path = Path(raw)
            files = sorted(path.glob("*.docx")) if path.is_dir() else [path]
            for file_path in files:
                report, md_path = convert(file_path, output, config)
                if md_path:
                    print("[{0}] {1} -> {2}".format(report.status, file_path.name, md_path))
                    for warning in report.warnings:
                        print("  {0}: {1}: {2}".format(warning.level, warning.kind, warning.detail))
                else:
                    print("[error] {0} conversion failed".format(file_path.name))
    elif args.command == "serve":
        from .server.app import main as serve_main

        serve_main(host=args.host, port=args.port)

    return 0
