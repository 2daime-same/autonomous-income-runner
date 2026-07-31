# Archimedes submission brief — MSN-00014

## Bounty

- Display ID: `MSN-00014`
- Title: `REST API for Engineering Unit Conversion`
- Public payout shown by the funded-bounty API: USD 100
- Escrow state observed before implementation: `locked`
- Deadline observed before implementation: `2026-08-21T23:59:59Z`

This document records implementation evidence only. It does **not** claim that Archimedes accepted the work or released payment.

## Deliverable

A standalone FastAPI service that converts engineering units locally across all eight requested domains. The service includes:

- `GET /domains`
- `GET /units?domain=...`
- `GET /convert?...`
- `POST /convert`
- generated OpenAPI documentation
- a non-root Docker image definition with health check
- an MIT license
- a reproducible test suite

## Requirements traceability

| Bounty requirement | Evidence |
|---|---|
| 8 domains | Registry and `/domains`; tests assert the exact eight-domain set |
| Minimum 50 unit pairs | Registry exposes 344 undirected / 688 directed compatible pairs |
| Local conversion, no external API | Exact constants and affine transforms in `app/conversions.py` |
| 30+ test cases | 79 collected tests, including exhaustive compatible-pair round trips |
| Dockerfile | `Dockerfile`, based on Python 3.12 slim and running as an unprivileged user |
| README/API documentation | `README.md`, generated OpenAPI, Swagger `/docs`, ReDoc `/redoc` |
| One validated pair per domain | Reference-value and API tests cover every domain |
| Accuracy within 0.1% | Decimal arithmetic; reference tolerances are substantially tighter than 0.1% |

## Verification commands

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
curl 'http://127.0.0.1:8000/convert?domain=pressure&from_unit=psi&to_unit=kPa&value=35'
```

```bash
docker build -t engineering-unit-api .
docker run --rm -p 8000:8000 engineering-unit-api
```

## Submission package

The repository workflow creates a deterministic ZIP archive and a SHA-256 manifest after tests pass. Platform account creation, terms acceptance, geographic eligibility, Stripe identity verification, final upload, and payout remain human-controlled actions.
