"""Model labelers ("LLM judges"): something that looks at an item and picks a label.

Two kinds:

- `SimulatedJudge` needs no API key and gives the same answer for the same item every
  time, so the public demo and the tests are reproducible. Its versions behave
  differently on purpose: `sim-judge-v2` is the "quiet model update" that breaks a few
  classes while overall accuracy still looks fine at a glance.
- `ClaudeJudge` asks Claude to classify the image. It runs only when you ask for it
  (`python -m app.judge --provider anthropic`) and needs `ANTHROPIC_API_KEY` and the
  optional `anthropic` package (`uv sync --extra llm`).

A judge's `version` is stored on every label it gives, so a version change is visible on
its control chart and becomes a `model_update` event for root-cause analysis.
"""

import base64
import hashlib
import json
import mimetypes
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings


class Judge(Protocol):
    version: str

    def label(self, payload: dict[str, Any], options: list[str]) -> str: ...


@dataclass(frozen=True)
class JudgeBehavior:
    """How a simulated model version answers."""

    accuracy: float
    # Classes this version gets wrong far more often, and what it answers instead.
    confusions: dict[str, str] = field(default_factory=dict)
    confused_accuracy: float = 0.3


SIM_VERSIONS: dict[str, JudgeBehavior] = {
    "sim-judge-v1": JudgeBehavior(accuracy=0.94),
    # The quiet regression: cats read as dogs, dogs as cats, trucks as cars.
    "sim-judge-v2": JudgeBehavior(
        accuracy=0.94,
        confusions={"cat": "dog", "dog": "cat", "truck": "automobile"},
    ),
}


def _unit(*parts: object) -> float:
    """A number in [0, 1) fixed by its inputs: the simulated judge's coin flip."""
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


class SimulatedJudge:
    """Deterministic stand-in for an LLM. `truth` returns an item's real class (the
    simulation knows it); without it, the judge can only guess."""

    def __init__(self, version: str, truth: Callable[[dict[str, Any]], str | None]):
        if version not in SIM_VERSIONS:
            raise ValueError(f"unknown simulated version {version!r}")
        self.version = version
        self.behavior = SIM_VERSIONS[version]
        self.truth = truth

    def label(self, payload: dict[str, Any], options: list[str]) -> str:
        key = json.dumps(payload, sort_keys=True)
        truth = self.truth(payload)
        if truth not in options:
            return options[int(_unit(self.version, key, "guess") * len(options))]
        confused_with = self.behavior.confusions.get(truth)
        if confused_with is not None:
            if _unit(self.version, key) < self.behavior.confused_accuracy:
                return truth
            return confused_with
        if _unit(self.version, key) < self.behavior.accuracy:
            return truth
        wrong = [o for o in options if o != truth]
        return wrong[int(_unit(self.version, key, "wrong") * len(wrong))]


DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public"


class ClaudeJudge:
    """Classifies an image item with Claude. The model id is the judge's version, so
    switching GAUGE_JUDGE_MODEL shows up as a model update on the charts."""

    def __init__(self, model: str | None = None, client: Any = None):
        self.version = model or os.environ.get("GAUGE_JUDGE_MODEL", DEFAULT_CLAUDE_MODEL)
        if client is None:
            try:
                import anthropic
            except ImportError as e:
                raise SystemExit("Install the LLM extra first: uv sync --extra llm") from e
            client = anthropic.Anthropic()
        self.client = client

    def label(self, payload: dict[str, Any], options: list[str]) -> str:
        if "image_url" not in payload:
            raise ValueError("ClaudeJudge labels image classification items only")
        response = self.client.messages.create(
            model=self.version,
            max_tokens=1024,
            output_config={
                "effort": "low",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {"label": {"type": "string", "enum": options}},
                        "required": ["label"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[
                {
                    "role": "user",
                    "content": [
                        _image_block(payload["image_url"]),
                        {
                            "type": "text",
                            "text": "Classify this image. It shows exactly one of: "
                            + ", ".join(options)
                            + ". Answer with the one label that fits best.",
                        },
                    ],
                }
            ],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("The model declined to label this item")
        text = next(b.text for b in response.content if b.type == "text")
        value = json.loads(text)["label"]
        if value not in options:
            raise RuntimeError(f"The model answered {value!r}, not one of the options")
        return value


def _image_block(url: str) -> dict[str, Any]:
    """Public URLs go to the API as they are; site paths like /cifar/00001.png are read
    from the built frontend (or frontend/public in a checkout) and sent inline."""
    if url.startswith(("http://", "https://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    root = get_settings().frontend_dist or PUBLIC_DIR
    path = (root / url.lstrip("/")).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise FileNotFoundError(f"No image at {url}")
    media_type = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
