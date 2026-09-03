# Baseline measurements

Fill this in **before** you change anything. These numbers are your
reference point for every optimization or migration decision you make
later - without them you're just guessing whether something got better
or worse.

Measured with `scripts/measure_baseline.sh`, which drives the whole
sequence below end to end against a single running replica: a full
`docker compose down -v` / `up -d` cycle for cold start, a fresh
`seed_data` run timed from an empty database, `curl`-based per-endpoint
latency sampling (with a real logged-in session + CSRF handling for the
endpoints that need one), and `pg_dump`/`pg_restore` against that same
freshly seeded data. Run it again any time you want fresh numbers.

## Environment

| Field | Value |
|---|---|
| Date measured | 2026-09-03 |
| Git commit | `005e057` |
| Host machine (CPU / RAM) | 12 CPU / 14 GiB RAM, Ubuntu 26.04 LTS, kernel 7.0.0-30-generic, no Docker CPU/memory limits set on any service |
| `docker compose` version | v5.3.1 |
| Number of `web` replicas | 1 |

## Cold start

| Measurement | Value |
|---|---|
| Time from `docker compose up` to first successful `/health/` response | 7.66s |
| Time from `docker compose up` to first successful `/` response | 7.69s |

## Endpoint latency (single replica, idle system)

Each row is `n` sequential single-client `curl` requests against a
warmed-up server; every request's status was checked and non-200s were
excluded from the timing (none occurred - see Error rate). p99 is
reported as `n/a` wherever the sample size makes the 99th-percentile
rank equal the max sample (true for every row here at n≤60, by
nearest-rank: `ceil(0.99*n) == n` for all n≤100).

| Endpoint | Method / n | p50 (ms) | p95 (ms) | p99 (ms) | Error rate |
|---|---|---|---|---|---|
| `GET /` | curl, n=60 | 21.66 | 22.90 | n/a | 0% (60/60) |
| `GET /products/` | curl, n=60 | 25.01 | 26.08 | n/a | 0% (60/60) |
| `GET /products/<slug>/` | curl, n=60 | 7.07 | 7.54 | n/a | 0% (60/60) |
| `POST /cart/add/<id>/` | curl, n=60, one distinct in-stock product per request | 8.04 | 9.26 | n/a | 0% (60/60) |
| `POST /orders/checkout/` | curl, n=20, add-then-checkout per iteration, only checkout POST timed | 9.35 | 10.13 | n/a | 0% (20/20) |
| `GET /reports/sales/` | curl, n=5, authenticated (`@login_required`) | 8875.72 | 9075.21 | n/a | 0% (5/5) |

## Interference

| Scenario | `browse.js` p95 before | `browse.js` p95 while `report.js` runs concurrently |
|---|---|---|
| Single replica | | |

*(Not remeasured by `scripts/measure_baseline.sh` - it only exercises
per-endpoint latency, not concurrent-load interference. Use
`loadtest/browse.js` + `loadtest/report.js` via k6 for this row; see
`docs/BASELINE-REFERENCE.md` and `VERIFICATION.md` check C9 for how it
was done previously.)*

## Data operations

| Measurement | Value |
|---|---|
| `seed_data` duration (fresh DB) | 77.7s |
| Row count: `auth_user` | 20,001 |
| Row count: `catalog_product` | 50,000 |
| Row count: `orders_order` | 200,000 immediately after seeding (the checkout-latency sampling above then added 20 more real orders before the DB-size/dump numbers below were taken) |
| Row count: `orders_orderitem` | 600,024 |
| Row count: `payments_payment` | 200,000 (matches `orders_order` 1:1 at seed time) |
| Database size on disk (`pg_database_size`) | 185 MB (194,067,479 bytes) - measured after the +20 orders from checkout sampling |
| `pg_dump` duration (full DB, custom format `-Fc`) | 2.16s |
| `pg_dump` output size | 21 MB (21,618,587 bytes) |
| `pg_restore` duration (into empty DB, same Postgres instance) | 2.12s |

## Session integrity

| Scenario | `session-integrity.js` result |
|---|---|
| 1 replica | |
| 3 replicas | |

*(Not remeasured here - requires k6 against a scaled stack; see
`docs/BASELINE-REFERENCE.md` and `VERIFICATION.md` checks C4/C5 for how
it was done previously.)*

---

## Comparison with `docs/BASELINE-REFERENCE.md`

**These two measurements are actually the same machine** - identical
CPU count (12), RAM (~14-14.77 GiB, same rounding), kernel
(`7.0.0-30-generic`), OS (Ubuntu 26.04), and `docker compose` version
(v5.3.1) on both. So this isn't really a cross-hardware comparison; it's
two runs of the same benchmark on the same box roughly a day apart, and
the "plausible hardware difference" the exercise normally asks you to
watch for doesn't really apply - any large gap here would point at a
regression or environmental noise (background load, disk cache state),
not different silicon.

| Measurement | Reference (2026-09-02) | This run (2026-09-03) | Gap |
|---|---|---|---|
| Cold start → `/health/` | 7.42s | 7.66s | +3% - noise |
| Cold start → `/` | 7.47s | 7.69s | +3% - noise |
| `GET /` p50 / p95 | 21.6 / 22.6 ms | 21.66 / 22.90 ms | <2% - noise |
| `GET /products/` p50 / p95 | 25.4 / 30.4 ms | 25.01 / 26.08 ms | p95 down ~14% - within normal run-to-run variance for a tail statistic at n=60, not flagged |
| `GET /products/<slug>/` p50 / p95 | 6.8 / 7.6 ms | 7.07 / 7.54 ms | <4% - noise |
| `POST /cart/add/<id>/` p50 / p95 | 8.4 / 9.7 ms | 8.04 / 9.26 ms | <5% - noise |
| `POST /orders/checkout/` p50 / p95 | 10.2 / 11.2 ms | 9.35 / 10.13 ms | ~8-10% faster - noise |
| `GET /reports/sales/` (median) | ~9.0s | ~8.88-9.08s | <2% - noise, this endpoint's cost is dominated by the same CPU-bound aggregation both times |
| `seed_data` duration | 75.8-77.8s | 77.7s | within the reference's own run-to-run range |
| Database size | 186 MB | 185 MB | <1% - noise |
| `pg_dump` duration / size | 2.29s / 21 MB | 2.16s / 21 MB | <6% / same - noise |
| `pg_restore` duration | 2.12s | 2.12s | identical |

**No endpoint's gap exceeds ~15%, and every one of those is well inside
ordinary run-to-run variance** (background load, OS disk cache state,
JIT/query-plan warm-up differences) for a single-client `curl` sampling
methodology - nothing here would survive a second re-run as a real
signal. Nothing is flagged as an actual regression or anomaly. The one
number worth a mention rather than a flag: `GET /products/` p95 dropped
from 30.4ms to 26.08ms, a bigger swing than the rest of the table, but
still small in absolute terms (4ms) and p95 at n=60 is a noisy
statistic (it's the 57th-fastest of 60 samples - a single slow request
either way moves it several percentage points).
