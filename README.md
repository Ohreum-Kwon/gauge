# Gauge

A data-labeling platform that monitors labeler quality the way a factory monitors a
production line.

Training data is only as good as the people who label it. Gauge mixes hidden **gold
questions** (known answers) into each labeler's queue, sends some items to several
labelers to measure **agreement**, and puts every labeler's error rate on a **control
chart**, so someone drifting out of control gets flagged before their labels reach the
dataset. The name comes from *Gauge R&R*, the measurement-system analysis quality
engineers use on factory gauges.

> **Status:** step 2 of 4. Labeling, gold mixing, overlap, agreement and control charts
> work through the API. Dashboards for them are next.

## Stack

| Layer | Tools |
|---|---|
| API | Python 3.12, FastAPI, SQLModel, Alembic, Pydantic, JWT auth with roles |
| Database | Postgres 16 |
| Frontend | React, TypeScript, Vite, TanStack Query, React Router |
| Tests and CI | pytest against real Postgres, Vitest with Testing Library, ruff, oxlint, Prettier, GitHub Actions |

## Run it locally

With Docker:

```sh
docker compose up --build
```

Open http://localhost:5173 and pick a demo account. The API docs are at
http://localhost:8000/api/docs.

Without Docker (needs Postgres running locally, plus [uv](https://docs.astral.sh/uv/)
and Node 22 or newer):

```sh
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.seed      # demo accounts and the CIFAR-10 demo project
uv run python -m app.simulate  # a simulated week of labeling (about two minutes)
uv run uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev
```

### Demo data

`uv run scripts/fetch_cifar_sample.py` downloads 300 CIFAR-10 test images (30 per class)
into `frontend/public/cifar/`, and writes `backend/sample_data/cifar10_sample.csv`. Three
images per class carry their true label as a gold answer, and every row has its true
label in `true_label` for the simulation. The seed script loads that file into the demo
project.

Demo accounts all use the password `gauge-demo`:

| Email | Role |
|---|---|
| admin@gauge.dev | Admin: creates projects, uploads items, assigns members |
| labeler1@gauge.dev … labeler4@gauge.dev | Labeler: works through a queue |
| reviewer@gauge.dev | Reviewer: resolves flagged items (coming in step 3) |
| sim-reliable, sim-noisy, sim-drifter, sim-rusher @gauge.dev | Simulated labelers |

## How quality is measured

| Signal | How |
|---|---|
| **Accuracy** | Each request draws a gold item (known answer) with probability `gold_rate`. Labelers can't tell gold from regular items, so gold accuracy is an honest sample of their work. |
| **Drift** | A [p-chart](https://en.wikipedia.org/wiki/P-chart) per labeler: gold error rate per day, with 3-sigma limits around the project's `target_error_rate`. The four [Western Electric rules](https://en.wikipedia.org/wiki/Western_Electric_rules) flag a labeler as out of control. The center line is a target, not the labeler's own average, so someone who is consistently bad is flagged too. |
| **Agreement** | A share (`overlap_rate`) of regular items go to `overlap_labelers` people. Fleiss' kappa covers the project; Cohen's kappa covers each pair of labelers. |
| **Speed** | Median time per label, and the share of labels under one second (rushing). |

The statistics live in `backend/app/stats.py` as pure functions, tested against textbook
examples (Fleiss 1971, among others).

### The drift demo

`uv run python -m app.simulate` labels for a simulated week with four labelers, through
the real queue: one reliable (95% right), one noisy (70%), one who drifts from 95% to 60%
on day 6, and one who clicks the first option in half a second every time. The drifter's
chart goes out of control on day 6, which a slow test in CI checks on every push.

## Tests

```sh
cd backend && uv run pytest        # needs a gauge_test database; see tests/conftest.py
cd backend && uv run pytest -m slow   # the full simulation, about two minutes
cd frontend && npm test
```

The backend tests run against Postgres, not SQLite, because the labeling queue relies
on Postgres row locks (`SELECT … FOR UPDATE SKIP LOCKED`) so two labelers asking at the
same moment never get the same item. Each test runs in a transaction that is rolled
back afterwards.

CI also runs `alembic check`, which fails if the models and migrations drift apart.

## Uploading items

CSV or JSON with these fields. Rows with a `gold_answer` become gold items. An upload is
all-or-nothing, and errors name the row that failed.

| Task type | Fields |
|---|---|
| Image classification | `image_url`, `gold_answer` (optional) |
| Pairwise preference | `prompt`, `response_a`, `response_b`, `gold_answer` (optional) |

## Layout

```
backend/
  app/
    models.py         tables
    schemas.py        API request/response bodies (kept apart so hashes and gold answers can't leak)
    routers/          auth, users, projects, labeling
    stats.py          kappa, p-charts, Western Electric rules (pure functions)
    services/         queue selection, quality reports, file ingest, audit log
    simulate.py       simulated labelers for the drift demo
  alembic/            migrations
  tests/
frontend/
  src/
    api.ts            typed API client
    auth.tsx          token and current-user context
    pages/            login, projects, project admin, labeling
scripts/              demo data
```

## Roadmap

1. **Skeleton:** auth with roles, projects, upload, labeling UI, CI
2. **Quality engine** (this step): gold mixing, overlap assignment, accuracy, Cohen's and Fleiss'
   kappa, p-charts with Western Electric rules, simulated labelers
3. **Dashboards and review:** per-labeler control charts, drift alerts, reviewer queue,
   audit log viewer
4. **Ship it:** deploy on Render and Neon, demo GIF, architecture diagram, design notes
