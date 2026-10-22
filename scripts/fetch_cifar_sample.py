# /// script
# requires-python = ">=3.12"
# dependencies = ["pyarrow"]
# ///
"""Download a small, class-balanced CIFAR-10 sample for the demo project.

    uv run scripts/fetch_cifar_sample.py

Writes the PNGs to frontend/public/cifar/ (the frontend serves them) and an item file
to backend/sample_data/cifar10_sample.csv (the seed script loads it). The first
GOLD_PER_CLASS images of each class carry their true label as a gold answer; every row
has its true label in true_label, which upload ignores and the labeler simulation uses.
"""

import csv
import io
import urllib.request
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

URL = (
    "https://huggingface.co/datasets/uoft-cs/cifar10/resolve/main/"
    "plain_text/test-00000-of-00001.parquet"
)
CLASSES = [
    "airplane", "automobile", "bird", "cat", "deer",
    "dog", "frog", "horse", "ship", "truck",
]  # fmt: skip
PER_CLASS = 30
GOLD_PER_CLASS = 3

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "frontend" / "public" / "cifar"
CSV_PATH = ROOT / "backend" / "sample_data" / "cifar10_sample.csv"


def main() -> None:
    print(f"Downloading {URL}")
    with urllib.request.urlopen(URL) as response:
        table = pq.read_table(io.BytesIO(response.read()))

    image_column = next(name for name in table.column_names if name != "label")
    images = table.column(image_column).to_pylist()
    labels = table.column("label").to_pylist()

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    taken: dict[int, int] = defaultdict(int)
    rows = []
    for index, (image, label) in enumerate(zip(images, labels, strict=True)):
        if taken[label] >= PER_CLASS:
            continue
        filename = f"{index:05d}.png"
        (IMAGE_DIR / filename).write_bytes(image["bytes"])
        gold = CLASSES[label] if taken[label] < GOLD_PER_CLASS else ""
        rows.append(
            {"image_url": f"/cifar/{filename}", "gold_answer": gold, "true_label": CLASSES[label]}
        )
        taken[label] += 1
        if len(rows) == PER_CLASS * len(CLASSES):
            break

    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["image_url", "gold_answer", "true_label"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} images to {IMAGE_DIR} and {CSV_PATH}")


if __name__ == "__main__":
    main()
