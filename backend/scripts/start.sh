#!/bin/sh
# Container entrypoint: migrate, optionally load the demo, then serve.
#
# With GAUGE_DEMO=1 it creates the demo accounts and projects, and runs the labeling
# simulation in the background so the server answers health checks right away. The
# simulation skips itself once a full week exists, and redoes a week cut short.
set -e

alembic upgrade head

if [ "$GAUGE_DEMO" = "1" ]; then
  python -m app.seed
  python -m app.simulate &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
