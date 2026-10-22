"""Parse uploaded item files (CSV or JSON) into item rows.

Both formats use the same flat fields, so a spreadsheet export and a script's JSON dump
work the same way. Every row is checked before anything is written: an upload is all or
nothing, and the error names the row that failed.
"""

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

from app.models import TaskType

# Fields each task type needs, in the order they're stored in the payload.
PAYLOAD_FIELDS: dict[TaskType, tuple[str, ...]] = {
    TaskType.image_classification: ("image_url",),
    TaskType.pairwise_preference: ("prompt", "response_a", "response_b"),
}

MAX_ROWS = 10_000


class IngestError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedItem:
    payload: dict[str, Any]
    gold_answer: str | None


def parse_items(
    filename: str, content: bytes, task_type: TaskType, label_options: list[str]
) -> list[ParsedItem]:
    rows = _read_rows(filename, content)
    if not rows:
        raise IngestError("The file has no rows")
    if len(rows) > MAX_ROWS:
        raise IngestError(f"The file has {len(rows)} rows; the limit is {MAX_ROWS}")
    return [_parse_row(i, row, task_type, label_options) for i, row in enumerate(rows, start=1)]


def _read_rows(filename: str, content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise IngestError("The file must be UTF-8 text") from e

    name = filename.lower()
    if name.endswith(".csv"):
        return list(csv.DictReader(io.StringIO(text)))
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise IngestError(f"Invalid JSON: {e.msg} (line {e.lineno})") from e
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise IngestError("JSON must be an array of objects")
        return data
    raise IngestError("Upload a .csv or .json file")


def _parse_row(
    row_number: int, row: dict[str, Any], task_type: TaskType, label_options: list[str]
) -> ParsedItem:
    payload: dict[str, Any] = {}
    for field in PAYLOAD_FIELDS[task_type]:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise IngestError(f"Row {row_number}: '{field}' is missing")
        payload[field] = value.strip()

    if task_type == TaskType.image_classification and not _looks_like_image_url(
        payload["image_url"]
    ):
        raise IngestError(f"Row {row_number}: image_url must start with http(s):// or /")

    gold = row.get("gold_answer")
    gold = gold.strip() if isinstance(gold, str) and gold.strip() else None
    if gold is not None and gold not in label_options:
        raise IngestError(
            f"Row {row_number}: gold_answer '{gold}' is not one of {', '.join(label_options)}"
        )
    return ParsedItem(payload=payload, gold_answer=gold)


def _looks_like_image_url(url: str) -> bool:
    return url.startswith(("http://", "https://", "/"))
