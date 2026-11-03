#!/bin/sh
# Container entrypoint: migrate, optionally load the demo, then serve.
#
# With GAUGE_DEMO=1 it creates the demo accounts and projects, and runs the labeling and
# panel line simulations in the background so the server answers health checks right
# away. Each simulation skips itself once a full week exists, and redoes a week cut short.
set -e

alembic upgrade head

if [ "$GAUGE_DEMO" = "1" ]; then
  python -m app.seed
  python -m app.simulate &
  python -m app.panel_sim &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
