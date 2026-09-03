# Baseline measurements — reference numbers (facilitator/auditor copy)

**This is not the file interns fill in.** That's `docs/BASELINE.md`,
which ships blank on purpose so each intern measures their own
hardware. This file is the auditor's own numbers, captured during the
`VERIFICATION.md` audit pass, kept as a sanity-check reference for
facilitators - a rough sense of "does this number look right" rather
than a value to hand to interns directly.

Do not copy these numbers into `docs/BASELINE.md` for an intern cohort.
Re-measuring on your own hardware is the point of the exercise.

## Environment

| Field | Value |
|---|---|
| Date measured | 2026-09-02 |
| Git commit | `dcdae42` ("initial commit") |
| Host machine (CPU / RAM) | 12 CPU / ~14.77 GiB RAM, Ubuntu 26.04, kernel 7.0.0-30-generic, no Docker CPU/memory limits set on any service |
| `docker compose` version | v5.3.1 |
| Number of `web` replicas | 1 |

## Cold start

| Measurement | Value |
|---|---|
| Time from `docker compose up` to first successful `/health/` response | 7.42s |
| Time from `docker compose up` to first successful `/` response | 7.47s |

## Endpoint latency (single replica, idle system)

Per-endpoint rows below were measured with 60 sequential single-client
`curl` requests each (n=20 for checkout, since each iteration creates a
real order and consumes stock) rather than k6, to get a clean
per-URL breakdown - k6's `browse.js`/`checkout.js`/`report.js` mix
several endpoints into one aggregate `http_req_duration`. Both are
reported.

| Endpoint | Method | p50 (ms) | p95 (ms) | p99 (ms) | Error rate |
|---|---|---|---|---|---|
| `GET /` | curl, n=60 | 21.6 | 22.6 | 28.1 | 0% |
| `GET /products/` | curl, n=60 | 25.4 | 30.4 | 50.4 | 0% |
| `GET /products/<slug>/` | curl, n=60 | 6.8 | 7.6 | 8.6 | 0% |
| `POST /cart/add/<id>/` | curl, n=60 | 8.4 | 9.7 | 10.9 | 0% |
| `POST /orders/checkout/` | curl, n=20 | 10.2 | 11.2 | 11.2 | 0% |
| `GET /reports/sales/` | curl, n=5 (solo, no concurrent load) | ~9.0s (median) | n/a (n too small) | n/a | 0% |

k6 aggregate runs (mixed endpoints per script, 20/5/3 VUs respectively, 1-2 min):

| Script | VUs | p50 (ms) | p95 (ms) | max (ms) | Error rate |
|---|---|---|---|---|---|
| `browse.js` (alone) | 20 | 27.2 | 34.7 | 483.7 | 0% |
| `checkout.js` (alone) | 5 | 10.5 | 107.5 | 199.4 | 0% |
| `report.js` (alone, 3 concurrent report requests) | 3 | 126ms | 25.9s | 26.0s | 0% (all succeed, just very slow) |

## Interference

| Scenario | `browse.js` p95 before | `browse.js` p95 while `report.js` runs concurrently |
|---|---|---|
| Single replica | 34.7ms (34.66ms and 40.34ms across two separate runs) | 3.67s (3.77s in a repeat run) |

Control test: two concurrent `browse.js` instances (no `report.js` involved,
effectively doubling ordinary lightweight load to 40 VUs) produced p95 =
40.34ms / 34.38ms - i.e. no meaningful degradation. This isolates the
cause of the 34ms→3.67s collapse above to the report endpoint's CPU cost
specifically, not merely "too much concurrent traffic." See
`VERIFICATION.md` check C9 for the full reasoning, including a caveat
about how this interacts with the single-gunicorn-worker-process
configuration.

## Data operations

| Measurement | Value |
|---|---|
| `seed_data` duration (fresh DB) | 75.8s (first run), 77.8s (re-run after `down -v`) |
| `seed_data` re-run duration (already seeded, idempotent) | 0.1s - 0.85s wall clock |
| Row count: `auth_user` | 20,001 (20,000 seeded + 1 `admin`) |
| Row count: `catalog_product` | 50,000 |
| Row count: `orders_order` | 200,000 immediately after seeding; 200,054 at time of this measurement (audit testing created ~54 additional real orders via checkout flow tests) |
| Row count: `orders_orderitem` | ~601,000-601,211 (varies slightly per seed run, spec target ~600,000) |
| Row count: `payments_payment` | matches `orders_order` 1:1 |
| Database size on disk (`pg_database_size`) | 186 MB |
| `pg_dump` duration (full DB, custom format `-Fc`) | 2.29s |
| `pg_dump` output size | 21 MB |
| `pg_restore` duration (into empty DB, same Postgres instance) | 2.12s |

## Session integrity

| Scenario | `session-integrity.js` result |
|---|---|
| 1 replica | PASS - 183/183 checks succeeded over 3 minutes |
| 3 replicas | FAIL - 93/183 checks succeeded; all 90 "item still in cart" checks failed (0%) |
