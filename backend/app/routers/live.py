"""The public live demo: a stream of samples over server-sent events, and faults the
visitor can inject into their own stream.

Sessions live in this process's memory. That is enough for one Render instance; with
more than one, a visitor's fault request could reach an instance that doesn't hold their
stream, and the sessions would need to move to something shared (Redis pub/sub, or
sticky routing by session id).
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from app.config import get_settings
from app.live import BASELINE_SAMPLES, Fault, LiveDemo

router = APIRouter(prefix="/live", tags=["live demo"])

HISTORY_SAMPLES = BASELINE_SAMPLES + 10  # sent at once, so charts start full

sessions: dict[str, LiveDemo] = {}


class FaultIn(BaseModel):
    fault: Fault
    target: str


class ResetIn(BaseModel):
    fault: Literal["reset"] = "reset"


def _has_room() -> None:
    # A dependency, so the 503 goes out before the event stream's headers do.
    if len(sessions) >= get_settings().live_max_sessions:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The live demo is full")


@router.get("/stream", response_class=EventSourceResponse, dependencies=[Depends(_has_room)])
async def stream() -> AsyncIterator[ServerSentEvent]:
    """Start a private live demo and stream it. The first event (`session`) carries the
    id that fault requests need and the chart layout; `history` carries the samples the
    control limits come from; then one `sample` event per tick until `end`."""
    settings = get_settings()
    session_id = secrets.token_urlsafe(12)
    demo = LiveDemo()
    sessions[session_id] = demo
    try:
        yield ServerSentEvent(event="session", data={"id": session_id, **demo.describe()})
        yield ServerSentEvent(event="history", data=[demo.step() for _ in range(HISTORY_SAMPLES)])
        for _ in range(settings.live_max_samples):
            await asyncio.sleep(settings.live_seconds_per_sample)
            yield ServerSentEvent(event="sample", data=demo.step())
        yield ServerSentEvent(event="end", data={"reason": "time limit"})
    finally:
        # Also runs when the visitor closes the tab and the stream is cancelled.
        sessions.pop(session_id, None)


@router.post("/{session_id}/faults", status_code=status.HTTP_204_NO_CONTENT)
async def inject(session_id: str, body: FaultIn | ResetIn) -> None:
    """Inject a fault into one visitor's stream, or clear them all with `reset`. Async on
    purpose: it runs on the event loop, between the stream's steps, never during one."""
    demo = sessions.get(session_id)
    if demo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No live session with that id")
    if isinstance(body, ResetIn):
        demo.reset()
        return
    try:
        demo.inject(body.fault, body.target)
    except KeyError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{body.fault.value} can't be applied to {body.target!r}",
        ) from None
