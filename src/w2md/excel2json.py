"""Excel workbook to JSON conversion."""

import json
import zipfile
from pathlib import Path

from .excel2csv import _read_sheets


def convert_excel_to_json(source, output_dir, mode="standard", preview_limit=200):
    source = Path(source)
    output_dir = Path(output_dir)
    if not source.is_file():
        raise FileNotFoundError("找不到待转换的 Excel 文件")

    output_dir.mkdir(parents=True, exist_ok=True)
    sheets = _read_sheets(source)
    results = []
    for index, sheet in enumerate(sheets):
        rows = sheet["rows"]
        column_count = max((len(row) for row in rows), default=0)
        headers = _build_headers(rows[0] if rows else [], column_count)
        records = _rows_to_records(rows[1:], headers)
        payload = records if mode == "standard" else {"list": records}

        json_path = output_dir / "{0}.json".format(_safe_name(sheet["name"], index))
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        preview_payload = records[:preview_limit] if mode == "standard" else {"list": records[:preview_limit]}
        results.append(
            {
                "name": sheet["name"],
                "json_path": json_path,
                "total_rows": len(records),
                "columns": column_count,
                "preview": json.dumps(preview_payload, ensure_ascii=False, indent=2),
            }
        )

    zip_path = output_dir / "all-sheets.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for result in results:
            archive.write(result["json_path"], result["json_path"].name)

    return results, zip_path


def _build_headers(first_row, column_count):
    headers = []
    used = set()
    for index in range(column_count):
        raw = first_row[index] if index < len(first_row) else None
        base = str(raw).strip() if raw is not None and str(raw).strip() else "column_{0}".format(index + 1)
        name = base
        suffix = 1
        while name in used:
            suffix += 1
            name = "{0}_{1}".format(base, suffix)
        used.add(name)
        headers.append(name)
    return headers


def _rows_to_records(rows, headers):
    records = []
    for row in rows:
        record = {}
        for index, header in enumerate(headers):
            value = row[index] if index < len(row) else None
            record[header] = _clean_value(value)
        records.append(record)
    return records


def _clean_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return None if value != value else value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_name(name, index):
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(name))
    cleaned = cleaned.strip("._")
    return cleaned or "sheet-{0}".format(index + 1)
