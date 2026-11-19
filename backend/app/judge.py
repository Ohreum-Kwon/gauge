"""Run a model labeler over the items people have labeled in a project.

    uv run python -m app.judge --project 3                      # simulated, no API key
    uv run python -m app.judge --project 3 --version sim-judge-v2
    uv run python -m app.judge --project 3 --provider anthropic --limit 50

The Anthropic provider needs ANTHROPIC_API_KEY and `uv sync --extra llm`; it labels with
GAUGE_JUDGE_MODEL (default claude-opus-5-5). Each run labels only items the judge hasn't
seen, so it is safe to run on a schedule.
"""

import argparse
import csv
from collections.abc import Callable
from typing import Any

from sqlmodel import Session

from app.db import get_engine
from app.judges import ClaudeJudge, Judge, SimulatedJudge
from app.models import Project
from app.seed import CIFAR_CSV
from app.services.judge import get_or_create_judge, items_to_judge, run_judge

SIM_JUDGE_EMAIL = "sim-judge@gauge.dev"
CLAUDE_JUDGE_EMAIL = "claude-judge@gauge.dev"


def cifar_truth() -> Callable[[dict[str, Any]], str | None]:
    """The sample's real classes by image URL: the simulated judge's "eyes"."""
    truth: dict[str, str] = {}
    if CIFAR_CSV.exists():
        with CIFAR_CSV.open() as f:
            truth = {r["image_url"]: r["true_label"] for r in csv.DictReader(f)}
    return lambda payload: truth.get(payload.get("image_url", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--project", type=int, required=True)
    parser.add_argument("--provider", choices=["simulated", "anthropic"], default="simulated")
    parser.add_argument("--version", default="sim-judge-v1", help="simulated version")
    parser.add_argument("--limit", type=int, help="label at most this many items")
    args = parser.parse_args()

    judge: Judge
    if args.provider == "anthropic":
        judge, email = ClaudeJudge(), CLAUDE_JUDGE_EMAIL
    else:
        judge, email = SimulatedJudge(args.version, cifar_truth()), SIM_JUDGE_EMAIL

    with Session(get_engine()) as session:
        project = session.get(Project, args.project)
        if project is None:
            raise SystemExit(f"No project {args.project}")
        user = get_or_create_judge(session, project, email)
        items = items_to_judge(session, project, user, limit=args.limit)
        count = run_judge(session, project, user, judge, items)
        print(f"{email} ({judge.version}) labeled {count} items")


if __name__ == "__main__":
    main()
