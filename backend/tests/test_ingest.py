import pytest

from app.models import TaskType
from app.services.ingest import IngestError, parse_items

OPTIONS = ["A", "B"]


def parse(filename: str, text: str, task_type=TaskType.image_classification, options=None):
    return parse_items(filename, text.encode(), task_type, options or ["cat", "dog"])


def test_csv_with_bom_and_blank_gold():
    items = parse("x.csv", "﻿image_url,gold_answer\n /a.png ,\n/b.png,dog\n")
    assert [i.payload for i in items] == [{"image_url": "/a.png"}, {"image_url": "/b.png"}]
    assert [i.gold_answer for i in items] == [None, "dog"]


def test_pairwise_rows_need_prompt_and_both_responses():
    good = '[{"prompt": "p", "response_a": "a", "response_b": "b", "gold_answer": "B"}]'
    items = parse("x.json", good, TaskType.pairwise_preference, OPTIONS)
    assert items[0].payload == {"prompt": "p", "response_a": "a", "response_b": "b"}

    with pytest.raises(IngestError, match="'response_b' is missing"):
        parse("x.json", '[{"prompt": "p", "response_a": "a"}]', TaskType.pairwise_preference)


@pytest.mark.parametrize(
    ("filename", "text", "message"),
    [
        ("x.txt", "image_url\n/a.png\n", "Upload a .csv or .json"),
        ("x.csv", "image_url\n", "no rows"),
        ("x.json", "{not json", "Invalid JSON"),
        ("x.json", '{"image_url": "/a.png"}', "array of objects"),
        ("x.csv", "image_url\nftp://a.png\n", "Row 1: image_url"),
        ("x.csv", 'image_url\n/a.png\n""\n', "Row 2: 'image_url' is missing"),
        ("x.csv", "image_url,gold_answer\n/a.png,horse\n", "'horse' is not one of cat, dog"),
    ],
)
def test_rejects_bad_files(filename, text, message):
    with pytest.raises(IngestError, match=message):
        parse(filename, text)


def test_rejects_non_utf8():
    with pytest.raises(IngestError, match="UTF-8"):
        parse_items("x.csv", b"\xff\xfe\x00", TaskType.image_classification, ["a"])
