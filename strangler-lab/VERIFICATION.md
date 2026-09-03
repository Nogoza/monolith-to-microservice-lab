# strangler-lab — Verification Report

Adversarial audit of the repo against its own build specification.
Every command below was actually executed against a live
`docker compose` stack on this machine (12 CPU / ~14.77 GiB RAM,
Ubuntu 26.04, kernel 7.0.0-30-generic, Docker Compose v5.3.1, no
per-container CPU/memory limits configured). Raw output is trimmed to
the relevant lines but not altered. Where a check flip-flopped between
runs (this happened - see A1, C8), both results are reported rather
than the more flattering one.

Git commit at time of original audit: `dcdae42` ("initial commit").

**This document has since been updated.** A follow-up pass fixed the
defects this audit found (README missing, `docs/BASELINE.md` filled in,
`seed_data` media idempotency, no restart policy on `web`, ambiguous
"restart" wording) and closed three gaps the original audit itself
missed (hardcoded-config verification, repo hygiene, and a cold-clone
smoke test). Every check the fixes could plausibly affect was re-run
against a live stack rather than assumed fixed — see **"Fixes applied"**
near the bottom for what changed and what proved it, and the sections
below marked **RE-VERIFIED** for the actual re-run output. Commit at
time of the fix pass: `f096ac5`.

## Summary

| ID | Check | Verdict |
|---|---|---|
| A1 | Media files exist on disk (50k product images) | **RE-VERIFIED PASS** — media-repair fix confirmed: recreate wipes `/app/media`, re-running `seed_data` restores all 50,000 files with zero DB rows touched |
| A2 | No persistence for `/app/media` or `/app/logs` | PASS |
| A3 | Gunicorn worker count ≥ 3 | **FAIL** — 1 worker process (4 threads), not 3+ processes. Intentional, see FACILITATOR-PRIVATE.md — not to be changed |
| A4 | Checkout is one atomic transaction over 4 tables, cross-app FKs exist | PASS |
| A5 | Hardcoded configuration (anti-pattern #6) | **PASS** (new check — audit originally skipped this anti-pattern entirely) |
| A6 | Repository hygiene | **PASS** (new check) |
| A7 | Cold-clone smoke test, README-only instructions | **PASS** (new check — most representative check in the report) |
| B | Concurrent migration race (3 containers, empty DB) | **RE-VERIFIED** — race still occurs (2/3 crash, unchanged — intentional, not fixed), but the stack now self-heals via `restart: on-failure` and converges to 3/3 in ~22s |
| C1 | `docker compose up` reachable, clean logs | **RE-VERIFIED PASS** |
| C2 | `seed_data` completes, row counts match, idempotent | **RE-VERIFIED PASS** |
| C3 | Full checkout flow, single instance | PASS (re-exercised as part of A7's cold-clone checkout) |
| C4 | `session-integrity.js` passes at 1 replica | PASS |
| C5 | `session-integrity.js` fails at 3 replicas | PASS (fails as designed) |
| C6 | Scheduler runs independently per replica | PASS |
| C7 | `/health/` lies while Postgres is down | PASS |
| C8 | Container restart empties `orders.log` | **RE-VERIFIED NUANCED** — false for `docker restart`, true for container recreation; unchanged after the fix pass (this was never touched, per instructions — only the wording pointing at it was clarified) |
| C9 | Report endpoint starves browse traffic | PASS, with a worker-count caveat — see detail. Not re-run (unaffected by the fixes) |
| D | Baseline numbers captured | DONE — split into `docs/BASELINE-REFERENCE.md` (these numbers) and a blank `docs/BASELINE.md` template — see Fixes applied |
| E | README leak check | **RE-VERIFIED PASS** — `README.md` now exists and contains none of the flagged terms |

---

## Part A

### A1. Media files actually exist on disk

**Command (run at time of writing this report, current live container):**
```
docker compose exec web sh -c 'ls /app/media | wc -l; du -sh /app/media'
```
**Output:**
```
0

4.0K	/app/media
```
**Verdict as literally run: FAIL.** Zero files present right now.

This is not the whole story, so here is the full sequence, in order:

1. Early in this audit, `A1` was first checked before anything else and
   also came back **0 files**, `4.0K`. At that point the product rows
   already existed in the DB from a prior session:
   ```
   docker compose exec db psql -U storefront storefront -c "select count(*), count(*) filter (where image is null or image='') from catalog_product;"
    products_with_image | products_without_image
   ----------------------+------------------------
                   50000 |                       0
   ```
   So the DB had 50,000 valid-looking image paths (`products/product-0.png`
   etc.) with zero backing files on disk.

2. As part of Part B (below), the Postgres volume was dropped
   (`docker compose down -v`) and `seed_data` was re-run against a fresh
   container. Immediately after that seed run:
   ```
   docker compose exec web sh -c 'find /app/media -type f | wc -l; du -sh /app/media'
   50000
   198M	/app/media
   ```
   **50,000 files, 198 MB — matches spec** (file count on the order of
   the product count, non-trivial total size).

3. Later, as part of check **C8** (below), `docker compose up -d
   --force-recreate web` was run to test log persistence. This
   recreated the container's writable layer, and the media files
   (never volume-mounted — see A2) were wiped again:
   ```
   docker compose exec web sh -c 'find /app/media -type f | wc -l'
   0
   ```
   The DB still shows all 50,000 `catalog_product.image` paths
   populated, because `seed_data`'s idempotency check is row-count
   based (`if Product.objects.count() >= PRODUCT_COUNT: skip`) — it has
   no way to detect that the physical files behind those paths are
   gone, so re-running it does **not** repair this.

**Source inspection** (`catalog/management/commands/seed_data.py`):
```python
def _build_placeholder_images():
    ...
    for color in PLACEHOLDER_COLORS:   # 10 solid-color templates
        buf = io.BytesIO()
        Image.new("RGB", (300, 300), color).save(buf, format="PNG")
        images.append(buf.getvalue())
    return images
...
image_bytes = placeholder_images[i % len(placeholder_images)]
product.image.save(f"product-{i}.png", ContentFile(image_bytes), save=False)
```
This writes **one physical file per product** (50,000 distinct
filenames), with content drawn from a rotating pool of 10 in-memory
template PNGs — not a symlink, not a single shared file, real bytes
written per file. The mechanism itself is correct; step 2 above proves
it produces the right file count and size on a freshly seeded,
never-recreated container.

**Final verdict at time of original audit: FAIL as measured**, with the
mechanism independently confirmed correct immediately post-seed.
Recorded as a defect and fixed — see "Fixes applied."

#### RE-VERIFIED after the fix (media-repair split from row-count check)

Full round trip on a freshly built, freshly seeded stack:
```
docker compose exec web python manage.py seed_data
...
Done in 77.4s
docker compose exec web sh -c 'find /app/media -type f | wc -l; du -sh /app/media'
50000
198M	/app/media
docker compose exec db psql -U storefront storefront -c "select 'products',count(*) from catalog_product union all select 'orders',count(*) from orders_order union all select 'orderitems',count(*) from orders_orderitem union all select 'payments',count(*) from payments_payment union all select 'users',count(*) from auth_user;"
  users      |  20001
  products   |  50000
  payments   | 200000
  orders     | 200000
  orderitems | 600037
```
Then, simulating an ordinary environment reset:
```
docker compose up -d --force-recreate web
docker compose exec web sh -c 'find /app/media -type f | wc -l'
0
docker compose exec db psql -U storefront storefront -c "select count(*) from catalog_product;"
50000
```
Media wiped, DB rows untouched — reproduces the original defect exactly.
Then the fix:
```
docker compose exec web python manage.py seed_data
Users already seeded (20001), skipping.
Categories already seeded (200), skipping.
Products already seeded (50000), skipping.
Repairing 50000 missing product image file(s)...
Repaired 50000 image file(s); no rows changed.
Orders already seeded (200000), skipping.
Done in 4.6s
docker compose exec web sh -c 'find /app/media -type f | wc -l; du -sh /app/media'
50000
198M	/app/media
```
Row counts after repair, byte-for-byte identical to before the recreate
(users 20001 / products 50000 / orders 200000 / orderitems 600037 /
payments 200000) — confirmed no row was touched.

**Verdict: RE-VERIFIED PASS.** The row-count check and the media check
now run independently (`seed_products` vs. the new `repair_missing_media`
step), so a normal `--force-recreate` reset self-heals on the next
`seed_data` run instead of leaving 50,000 broken images with no
explanation.

---

### A2. No persistence for `/app/media` or `/app/logs`

**Full `docker-compose.yml`:**
```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: storefront
      POSTGRES_USER: storefront
      POSTGRES_PASSWORD: storefront_pw
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U storefront"]
      interval: 5s
      timeout: 5s
      retries: 10

  web:
    build: .
    depends_on:
      db:
        condition: service_healthy

  nginx:
    image: nginx:1.25-alpine
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    ports:
      - "8000:80"
    depends_on:
      - web

volumes:
  pgdata:
```

- `/app/media`: no named volume, no bind mount. The `web` service has
  **no `volumes:` key at all**.
- `/app/logs`: same — no named volume, no bind mount.
- The only bind mount in the whole file is `./nginx/nginx.conf` into
  the `nginx` container, read-only, and it doesn't touch `web` at all.
- `db` has a named volume (`pgdata`) for Postgres's own data directory,
  which is unrelated to the app-level anti-pattern paths and is
  expected/correct (losing the actual database on every restart would
  make the whole exercise unusable, not harder).

**Verdict: PASS.** Neither path is backed by any volume or bind mount.
No broad `.:/app` development bind mount exists either.

---

### A3. Gunicorn worker count

**Where gunicorn is invoked** (`entrypoint.sh`, exact lines):
```sh
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 1 \
    --threads 4 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
```

**Command:**
```
docker compose exec web sh -c 'ps aux | grep gunicorn'
```
**Output:**
```
sh: 1: ps: not found
```
The image is `python:3.12-slim`; there is no `ps` binary. Fell back to
reading `/proc` directly:
```
docker compose exec web sh -c 'for p in /proc/[0-9]*; do tr "\0" " " < $p/cmdline 2>/dev/null; echo; done | grep gunicorn'
```
**Output:**
```
/usr/local/bin/python3.12 /usr/local/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 1 --threads 4 --timeout 60 --access-logfile - --error-logfile -
/usr/local/bin/python3.12 /usr/local/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 1 --threads 4 --timeout 60 --access-logfile - --error-logfile -
```
Two processes = one gunicorn **master** (pid 1, does not serve
requests) + one **worker** process running 4 threads. Actual concurrent
worker *process* count: **1**.

**Verdict against the stated PASS bar ("3 or more sync workers"): FAIL.**
This is a deliberate design choice from the original build (documented
in `FACILITATOR-PRIVATE.md`, not invented for this audit): a single
process is what makes the `LocMemCache` session anti-pattern (#1) and
the once-per-container scheduler (#4) work correctly at exactly 1
replica. But the audit's own stated reasoning for wanting 3+ workers is
legitimate and is addressed head-on in **C9** below with an actual
control experiment, not asserted away.

---

### A4. Checkout is one transaction spanning four tables

**Command:**
```
grep -rn "atomic" --include=*.py .
```
**Output:**
```
./catalog/management/commands/seed_data.py:258:            with transaction.atomic():
./cart/services.py:50:@transaction.atomic
./cart/services.py:83:@transaction.atomic
./cart/services.py:102:@transaction.atomic
./orders/services.py:40:@transaction.atomic
```

**Full checkout function** (`orders/services.py`):
```python
@transaction.atomic
def checkout(request, user, cart_items, shipping_address, payment_method):
    """
    The one transaction the whole store's data integrity rests on: stock,
    order, order items and payment all move together or not at all.
    """
    if not cart_items:
        raise EmptyCart()

    total = sum((item["subtotal"] for item in cart_items), start=0)

    order = Order.objects.create(
        user=user,
        status="pending",
        total=total,
        shipping_address=shipping_address,
    )

    for item in cart_items:
        product = Product.objects.select_for_update().get(pk=item["product"].id)
        quantity = item["quantity"]

        if product.stock < quantity:
            raise OutOfStock(product, product.stock)

        product.stock -= quantity
        product.reserved_stock = max(0, product.reserved_stock - quantity)
        product.save(update_fields=["stock", "reserved_stock"])

        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit_price=product.price,
        )

    payment = charge(order, payment_method, total)

    order.status = "paid"
    order.save(update_fields=["status"])

    _append_order_log(order, payment)

    release_all_reservations(request)

    return order
```
One `@transaction.atomic` decorator wraps the whole function. Inside it:
`Product.save()` (stock/inventory), `Order.objects.create()` +
`order.save()` (order), `OrderItem.objects.create()` (order items), and
`charge()` → `Payment.objects.create()` (payment) — all four tables,
one transaction. Confirmed by reading the source directly, not inferred.

**Cross-app foreign keys:**
```sql
SELECT tc.table_name, kcu.column_name, ccu.table_name AS references_table
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
ORDER BY 1;
```
```
         table_name          |   column_name   |  references_table
------------------------------+-----------------+---------------------
 accounts_profile             | user_id         | auth_user
 auth_group_permissions       | group_id        | auth_group
 auth_group_permissions       | permission_id   | auth_permission
 auth_permission               | content_type_id | django_content_type
 auth_user_groups              | user_id         | auth_user
 auth_user_groups              | group_id        | auth_group
 auth_user_user_permissions    | user_id         | auth_user
 auth_user_user_permissions    | permission_id   | auth_permission
 cart_cartreservation          | product_id      | catalog_product
 catalog_product               | category_id     | catalog_category
 django_admin_log              | content_type_id | django_content_type
 django_admin_log              | user_id         | auth_user
 orders_order                  | user_id         | auth_user
 orders_orderitem              | order_id        | orders_order
 orders_orderitem              | product_id      | catalog_product
 payments_payment              | order_id        | orders_order
(16 rows)
```
Cross-app: `orders_order.user_id → auth_user` (orders→accounts/auth),
`orders_orderitem.product_id → catalog_product` (orders→catalog),
`payments_payment.order_id → orders_order` (payments→orders),
`cart_cartreservation.product_id → catalog_product` (cart→catalog).
No app has its own isolated foreign-key island.

**Verdict: PASS.**

---

### A5. Hardcoded configuration (anti-pattern #6) — never checked by the original audit

The original audit verified five of the six anti-patterns (session,
media/logs, scheduler, sync report endpoint, migration race) and
skipped hardcoded configuration entirely. Closing that gap now.

**Source** (`config/settings.py`):
```python
SECRET_KEY = "django-insecure-8f2k4jz9q!x3m0t7v-storefront-prod-key-do-not-share"
DEBUG = True
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "storefront",
        "USER": "storefront",
        "PASSWORD": "storefront_pw",
        "HOST": "db",
        "PORT": "5432",
    }
}
```

| Field | Literal in `settings.py`? | Verdict |
|---|---|---|
| `DATABASES["default"]["HOST"]` | `"db"` | PASS |
| `DATABASES["default"]["NAME"]` | `"storefront"` | PASS |
| `DATABASES["default"]["USER"]` | `"storefront"` | PASS |
| `DATABASES["default"]["PASSWORD"]` | `"storefront_pw"` | PASS |
| `SECRET_KEY` | string literal | PASS |
| `DEBUG` | `True` literal | PASS |
| `ALLOWED_HOSTS` | `["*"]` literal | PASS |

**Operational proof** (the part that actually matters — no plumbing
exists to override any of this):
```
grep -rn "os.environ\|os.getenv\|environ.get\|django-environ\|dotenv" --include=*.py .
./manage.py:8:    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
./config/asgi.py:5:os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
./config/wsgi.py:5:os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
```
All three hits are Django's own boilerplate for selecting *which
settings module to import* (`DJANGO_SETTINGS_MODULE`) — not a read of
any database, secret, or debug value. No `os.environ`/`os.getenv`/
`django-environ`/`dotenv` usage exists anywhere in application code for
actual configuration values.
```
docker compose exec web env | grep -iE "postgres|secret|debug|database"
(no output)
find . -name ".env*" -not -path "./.git/*"
(no output)
```
No matching environment variables inside the running container, and no
`.env` file anywhere in the repo.

**Verdict: PASS on every sub-check.** Database credentials, secret key,
`DEBUG`, and `ALLOWED_HOSTS` are all string/bool literals in
`config/settings.py`, with zero 12-factor config plumbing anywhere in
the codebase to override them. Anti-pattern #6 is intact and correctly
implemented. Nothing changed by this fix pass — this was a
verification-only gap.

---

## Part B — Concurrent migration race

**Commands:**
```
docker compose down -v
docker compose up -d db          # wait for healthy
docker compose up -d --scale web=3 --no-recreate
```

**Result — not "succeeded cleanly," not "no effect observed." Two of
three containers crashed outright, ~15 seconds after everything was
seeded from an empty database:**

```
NAME                    STATUS
strangler-lab-web-1     Up (running)
strangler-lab-web-2     Exited (1)
strangler-lab-web-3     Exited (1)
```

Start timestamps (`docker inspect -f StartedAt`), all within 200ms of
each other:
```
web-1: 2026-09-02T14:54:31.995508228Z   (survived)
web-2: 2026-09-02T14:54:32.084593305Z   (FinishedAt 14:54:32.991094363Z, ExitCode 1)
web-3: 2026-09-02T14:54:32.18176388Z    (FinishedAt 14:54:33.082420398Z, ExitCode 1)
```

**web-2's crash** — failed creating the `django_migrations` table itself:
```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "pg_class_relname_nsp_index"
DETAIL:  Key (relname, relnamespace)=(django_migrations_id_seq, 2200) already exists.
...
django.db.migrations.exceptions.MigrationSchemaMissing: Unable to create the django_migrations table (duplicate key value violates unique constraint "pg_class_relname_nsp_index" ...)
```

**web-3's crash** — got partway through migrations, hit real DDL
interleaving with whichever container was concurrently mutating the
same table:
```
Applying admin.0003_logentry_add_action_flag_choices... OK
...
psycopg2.errors.UndefinedColumn: column "name" of relation "django_content_type" does not exist
...
django.db.utils.ProgrammingError: column "name" of relation "django_content_type" does not exist
  Applying contenttypes.0002_remove_content_type_name...
```

**web-1** applied all 23 migrations cleanly and started gunicorn normally.

**Self-recovery:** No. `docker-compose.yml` sets no `restart:` policy
(defaults to `no`). Waited 20+ seconds and re-checked:
```
strangler-lab-web-2   Exited (1) 53 seconds ago
strangler-lab-web-3   Exited (1) 53 seconds ago
```
Both stayed dead. In a plain `docker compose up --scale web=3` against
an empty database, **2 of 3 replicas simply never come up** and nothing
in this stack retries them. (A Kubernetes Deployment would keep
restarting the crashing pods per its own restart policy and would very
likely converge once web-1's migration finishes — this repo's plain
Compose setup has no equivalent, so this specific failure mode is worse
here than it would be on the actual target platform, which is worth
knowing rather than assuming away.)

**Restoration:** manually restarted the two dead containers — they
succeeded immediately, since the schema was already fully migrated by
web-1 by that point:
```
docker start strangler-lab-web-2 strangler-lab-web-3
# both: Up (no further errors)
```
Scaled back to 1 replica and re-ran `seed_data` (77.8s, matching row
counts — see C2 below) to restore a working dataset before continuing
the audit.

**Verdict: this is a real, reproducible failure, not a timing edge
case that merely "might" occur — it occurred on the first and only
attempt made in this session.**

**Not fixed, by design** — this is the intended teaching moment about
migrations in a multi-replica deployment. No locking was added, the
race still happens exactly as above.

#### RE-VERIFIED after adding `restart: on-failure` to the `web` service only

```
docker compose down -v
docker compose up -d --scale web=3
```
The race still occurs — two of three containers still crash on the
same migration-table conflicts as before:
```
docker inspect strangler-lab-web-2 --format '{{.RestartCount}}'   → 1
docker inspect strangler-lab-web-3 --format '{{.RestartCount}}'   → 1
docker inspect strangler-lab-web-1 --format '{{.RestartCount}}'   → 0
docker compose logs web | grep -iE "error|traceback"
web-3 | psycopg2.errors.UndefinedColumn: column "name" of relation "django_content_type" does not exist
web-2 | psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "pg_type_typname_nsp_index"
```
But this time, instead of staying dead, Compose's `restart: on-failure`
brought each crashed container back up exactly once, and the retry
succeeded because by then web-1 had finished migrating:
```
docker compose ps
strangler-lab-web-1   Up 23 seconds
strangler-lab-web-2   Up 21 seconds
strangler-lab-web-3   Up 21 seconds
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
200
```
**Timing:** stack reached 3/3 running (and stayed there) at **~22
seconds** after `up` was issued. **Restart cycles:** exactly 1 per
crashed container (web-2: 1, web-3: 1, web-1: 0) — no restart storms,
no flapping.

**Verdict: RE-VERIFIED.** The underlying race is untouched (correct —
it's the point of the exercise), but the stack no longer gets stuck at
1/3 capacity: it now self-heals in about 22 seconds with a single retry
per failed container, which is the realistic symptom a Kubernetes
Deployment's restart policy would also produce, rather than the
previous silent-permanent-failure mode that has no equivalent on the
target platform.

---

## Part C — Re-run of the original nine checks

All re-run against the restored, freshly-seeded, single-replica system
unless stated otherwise.

### C1. `docker compose up` → reachable, clean logs

```
docker compose down          # kept the pgdata volume this time
docker compose up -d
# poll /health/ and / until 200
```
```
compose up -d returned at 1788361049.48
health/ 200 first seen at 1788361050.92   (Δ 7.42s)
home  / 200 first seen at 1788361050.97   (Δ 7.47s)
```
`docker compose logs web/db/nginx --tail 60`: no application errors.
One transient line in the nginx log during the ~1s window before
gunicorn had bound its port:
```
nginx-1 | ... "GET /health/ HTTP/1.1" 502 ... connect() failed (111: Connection refused) ... upstream: "http://172.26.0.3:8000/health/"
nginx-1 | ... "GET /health/ HTTP/1.1" 200 ...
```
This is expected container-startup ordering, not an application bug —
noted rather than hidden.

**Verdict: PASS.**

#### RE-VERIFIED after the fix pass (fresh build, `restart: on-failure` now present)

```
docker compose up -d --build
docker compose ps
strangler-lab-db-1      Up (healthy)
strangler-lab-web-1     Up
strangler-lab-nginx-1   Up
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
200
docker compose logs web --tail 40
Applying database migrations... (all 23 OK)
Collecting static files... 127 static files copied
Starting gunicorn...
[INFO] Listening at: http://0.0.0.0:8000 (1)
[INFO] Using worker: gthread
[INFO] Booting worker with pid: 24
172.26.0.4 - - "GET / HTTP/1.0" 200 848
```
No errors in the logs, single replica came up clean. `restart:
on-failure` on a normal single-replica startup is a no-op, as expected
— it only ever engaged during the 3-replica migration race in Part B.

**Verdict: RE-VERIFIED PASS.**

### C2. `seed_data` completes, row counts match spec, idempotent

```
time docker compose exec web python manage.py seed_data
...
Done in 77.8s
real  1m18.570s
```
Row counts immediately after:
```
categories  |    200
users       |  20001
products    |  50000
payments    | 200000
orders      | 200000
order_items | 601157
```
Re-run (idempotency):
```
Users already seeded (20001), skipping.
Categories already seeded (200), skipping.
Products already seeded (50000), skipping.
Orders already seeded (200000), skipping.
Done in 0.1s
real  0m0.803s
```
Spec targets: 20,000 users / 200 categories / 50,000 products / 200,000
orders / ~600,000 order items / matching payments. All hit, well under
the 5-minute budget.

**Verdict: PASS.**

#### RE-VERIFIED after the fix pass (adds the media-repair step, A1)

```
time docker compose exec web python manage.py seed_data
...
Done in 77.4s
real  1m18.250s
```
Row counts: users 20001 / products 50000 / orders 200000 / orderitems
600037 / payments 200000 — matches spec. Re-run for idempotency:
```
Users already seeded (20001), skipping.
Categories already seeded (200), skipping.
Products already seeded (50000), skipping.
All product image files present, nothing to repair.
Orders already seeded (200000), skipping.
Done in 0.6s
```
The new media-repair step correctly no-ops (`All product image files
present, nothing to repair.`) when nothing is actually missing — it
only does work when the row check passes but files are gone (see A1's
re-verification for that path).

**Verdict: RE-VERIFIED PASS.**

### C3. Full checkout flow, single instance

Logged in as a seeded user via curl with a real CSRF/session cookie
flow, added a product to cart, checked out:
```
login: 302
add: 302
cart has item: YES
HTTP/1.1 302 Found
Location: /orders/200001/
```
```sql
select o.id,o.status,o.total,p.status,p.transaction_ref from orders_order o join payments_payment p on p.order_id=o.id where o.id=200001;
 200001 | paid | 445.19 | approved | txn_1ae80040025c41dd815a
```
```
docker compose exec web tail -3 /app/logs/orders.log
2026-09-02T14:57:49.588936+00:00 order=200001 user=43 total=445.19 status=paid txn=txn_1ae80040025c41dd815a
```

**Verdict: PASS.**

### C4. `session-integrity.js` PASSES at 1 replica

```
docker run --rm --network host -v "$(pwd)/loadtest":/scripts -e BASE_URL=http://localhost:8000 grafana/k6 run /scripts/session-integrity.js
```
```
checks_total.......: 183     1.011078/s
checks_succeeded...: 100.00% 183 out of 183
✓ item still in cart
```

**Verdict: PASS.**

### C5. `session-integrity.js` FAILS at 3 replicas

```
docker compose up -d --scale web=3 --no-recreate
# same k6 script, same target
```
```
checks_total.......: 183    1.010634/s
checks_succeeded...: 50.81% 93 out of 183
✗ item still in cart
  ↳  0% — ✓ 0 / ✗ 90
```

**Verdict: PASS (fails as designed).**

### C6. Scheduler runs independently per replica, 3 replicas, 5+ min wait

```
docker exec strangler-lab-web-1 cat /app/logs/scheduler.log
2026-09-02T15:02:30.616834+00:00 expire_abandoned_carts released=0

# (web-2/web-3 started ~3.5 min later than web-1; waited for their own 5-min mark)

docker exec strangler-lab-web-2 cat /app/logs/scheduler.log
2026-09-02T15:06:04.483281+00:00 expire_abandoned_carts released=0

docker exec strangler-lab-web-3 cat /app/logs/scheduler.log
2026-09-02T15:06:04.543554+00:00 expire_abandoned_carts released=0
```
Three independent timers, three independent log entries, none of them
coordinated with each other — web-2 and web-3 fired within 60ms of each
other only because they happened to start within 100ms of each other,
not because of any shared coordination.

**Verdict: PASS.**

### C7. `/health/` lies while Postgres is down

```
docker compose stop db
curl -s -o /dev/null -w "health: %{http_code}\n" http://localhost:8000/health/
curl -s -o /dev/null -w "home: %{http_code}\n" http://localhost:8000/
```
```
health: 200
home: 500
```
```
curl -s http://localhost:8000/health/
{"status": "ok"}
```

**Verdict: PASS.**

### C8. Container restart empties `orders.log`

This one needed two different interpretations of "restart" because they
give opposite results — reported both rather than picking one:

```
docker compose exec web wc -l /app/logs/orders.log
1 /app/logs/orders.log

# plain restart — same container, same writable layer
docker compose restart web
docker compose exec web wc -l /app/logs/orders.log
1 /app/logs/orders.log        # UNCHANGED

# recreate — new container, new writable layer
docker compose up -d --force-recreate web
docker compose exec web sh -c 'test -f /app/logs/orders.log && wc -l /app/logs/orders.log || echo "MISSING/EMPTY"'
MISSING/EMPTY
```
`docker restart` reuses the same container's filesystem layer, so a
plain restart does **not** demonstrate the anti-pattern — the log
survives untouched. Only actual container recreation (`--force-recreate`,
or the equivalent that happens on a real redeploy / pod replacement)
wipes it, because `/app/logs` is never volume-mounted (confirmed in A2).

Also observed as a side effect: this same `--force-recreate` wiped
`/app/media` again (see A1) — the two paths share the same root cause
and the same blast radius.

**Verdict: NUANCED, not a clean PASS/FAIL.** The literal instruction
("restart the web container") as most people would run it in Docker
Compose (`docker compose restart`) does **not** reproduce the claimed
symptom. Only recreation does. This is worth calling out explicitly for
interns and facilitators, since "restart" is ambiguous and the two
readings give opposite results.

#### RE-VERIFIED after the fix pass (wording disambiguated in FACILITATOR-PRIVATE.md, mechanism untouched)

```
docker compose exec web wc -l /app/logs/orders.log
1 /app/logs/orders.log
docker compose restart web
docker compose exec web wc -l /app/logs/orders.log
1 /app/logs/orders.log        # UNCHANGED
docker compose up -d --force-recreate web
docker compose exec web sh -c 'test -f /app/logs/orders.log && wc -l /app/logs/orders.log || echo MISSING'
MISSING
```
Identical result to the original audit — this check was never meant to
change behavior, only the prose pointing at it (`FACILITATOR-PRIVATE.md`
now says explicitly: use `docker compose up -d --force-recreate web`,
plain `docker compose restart` will not reproduce this).

**Verdict: RE-VERIFIED NUANCED — same as before, now correctly documented.**

### C9. Report endpoint interference — three numbers, plus the worker-count cross-check

**Three requested numbers:**
- `browse.js` p95 alone: **34.66ms** (repeat run: 40.34ms)
- `browse.js` p95 while `report.js` runs concurrently: **3.77s** (repeat run: 3.67s)
- Single solo report request wall-clock: **8.85s – 9.28s** across 6 separate solo measurements (one via `time curl`, five sequential samples: 9.28, 9.01, 8.91, 8.89, 9.00s)

```
docker run ... grafana/k6 run /scripts/browse.js        (alone)
✓ 'p(95)<500' p(95)=34.66ms

docker run ... grafana/k6 run /scripts/report.js &       (background, 3 VUs)
docker run ... grafana/k6 run /scripts/browse.js          (foreground, 20 VUs)
✗ 'p(95)<500' p(95)=3.77s
```

**Cross-reference with A3 (1 worker process, 4 threads):** the audit's
own framing asks whether this proves the report endpoint is the cause,
or merely that there aren't enough workers for *any* concurrent load.
Tested this directly with a control: two concurrent `browse.js`
instances (no report load at all, doubling ordinary traffic to 40 VUs
against the same single-process/4-thread server):
```
browseA: p95=40.34ms
browseB: p95=34.38ms
```
Essentially unchanged from the 34.66ms single-instance baseline.
Ordinary lightweight concurrent load does **not** reproduce the
collapse. The 34ms→3.77s collapse only appears when `report.js` is in
the mix, which does isolate the cause to the report endpoint's CPU cost
specifically (it holds the GIL for most of its ~9s runtime, and Python
threads don't provide real parallelism for CPU-bound work), not to
"too few threads for any traffic."

**However**, the honest caveat the audit asked for: because there is
only **one** gunicorn worker *process* (A3), that GIL contention affects
100% of this container's request-serving capacity. With 3 separate
worker processes (as the original build's own facilitator notes and
this audit's A3 both flag as the untested assumption), a report request
landing in worker process 1 would only saturate that one process's
threads — the other 2 processes, each with their own GIL, would keep
serving browse traffic normally. So: **the mechanism demonstrated here
(CPU-bound work starving I/O-bound work sharing a GIL) is real and
confirmed by the control experiment, but the severity of the numbers
above (a ~100x p95 blowup, not a partial degradation) is inflated by
the single-worker-process configuration and would likely be less
dramatic — though probably still clearly present — with 3+ worker
processes.** Both things are true at once; reporting them separately
would have been misleading either way.

**Verdict: PASS, with the above caveat spelled out rather than omitted.**

---

## Part D — Baseline capture

**Updated:** the original audit filled its numbers directly into
`docs/BASELINE.md`, which works against that file's own stated purpose
("fill this in **before** you change anything" — i.e. it's meant to be
blank until an intern measures their own hardware). Fixed by moving the
auditor's filled-in numbers to a new `docs/BASELINE-REFERENCE.md`
(same table structure, plus the environment note that these are the
auditor's numbers on the auditor's machine, not a target to hit) and
resetting `docs/BASELINE.md` back to a blank template — every value
cell empty, with instructions at the top telling the reader to fill it
in themselves before changing anything. Verified:
```
head -20 docs/BASELINE.md
# Baseline measurements
Fill this in **before** you change anything...
| Date measured | |
| Git commit | |
...
grep -n '^| ' docs/BASELINE.md | grep -vE 'Field|Measurement|Endpoint|Scenario'
| Date measured | |
| Git commit | |
| Host machine (CPU / RAM) | |
... (every data row ends in empty cells; headers excluded above)
```
No populated data cells remain in `docs/BASELINE.md` — every row that
isn't a table header has empty value columns. The historical
numbers below are preserved for reference (now in
`docs/BASELINE-REFERENCE.md`), not duplicated further here. Headline
numbers (from the reference file):

- Cold start: 7.42s to `/health/` 200, 7.47s to `/` 200
- `catalog_list` p95: 30.4ms · `product_detail` p95: 7.6ms · `cart_add`
  p95: 9.7ms · `checkout` p95: 11.2ms (single sequential client) / 107.5ms
  (k6 `checkout.js`, 5 VUs, mixed endpoints) · `report` solo: ~9.0s median
- Database size: 186 MB (200k orders / 601k order items / 50k products / 20k users)
- `pg_dump -Fc`: 2.29s, 21 MB output
- `pg_restore` into empty DB: 2.12s

Hardware/config this was measured on: 12 CPU / ~14.77 GiB RAM host, no
Docker resource limits configured on any service — see `docs/BASELINE.md`
"Environment" table for the full record.

**Note:** filling in `docs/BASELINE.md` with real numbers was done
because this audit explicitly asked for it, but it works against the
file's own stated purpose ("Fill this in **before** you change
anything" — i.e., it's meant to be blank until an intern measures it
themselves). Flagged under Defects below rather than silently deciding
which instruction wins.

---

## Part E — README leak check

**Original finding:** `README.md` did not exist anywhere in the
repository or its git history. Filed as the top defect (see Fixes
applied) and written from scratch as a matter-of-fact, slightly
unhelpful developer-handover note — setup instructions, a domain
overview of the six Django apps, and a "known issues" section
containing only trivial cosmetic nitpicks (off-by-one catalog
pagination, missing image alt-text, admin UTC display), with zero
mention of the intentional anti-patterns or the training-exercise
framing.

#### RE-VERIFIED — leak check against the new README.md

```
grep -rniE "kubernetes|k8s|replica|scal|microservice|helm|pod|argo|strangler|monolith" README.md
```
```
(no output — grep exit code 1)
```
Zero matches against the full flagged-term list (including `strangler`
and `monolith`, which the original check list didn't even include but
which would be equally damaging leaks).

`docs/BASELINE.md`'s uses of "replica" remain, unchanged from the
original audit's finding — still not a leak, for the same reason as
before: it's a fill-in-the-numbers worksheet, not narrative prose, and
the leak constraint was scoped to the README's tone. This file is
gitignored from the intern's-eye-view narrative concern anyway since
it's an explicit measurement template, not onboarding copy.

**Verdict: RE-VERIFIED PASS.** `README.md` exists, is complete enough
to run the whole stack on (confirmed independently in **A7** below),
and leaks none of the flagged vocabulary.

---

## Part F — Gaps the original audit missed

### A6. Repository hygiene — never checked by the original audit

```
git status --porcelain
?? strangler-lab/VERIFICATION.md
```
Only this report itself is untracked, pending this update being
committed — no stray generated files, no accidental checked-in state.
```
git ls-files | wc -l
88
du -sh .git
1016K	.git
```
Small, clean history — no accidentally committed seed images or media
bloating the object store.
```
cat strangler-lab/.gitignore
__pycache__/
*.pyc
*.pyo
.Python
env/
venv/
.venv/
*.egg-info/
staticfiles/
media/
logs/
db.sqlite3
.DS_Store
*.log

FACILITATOR-PRIVATE.md
```
```
git ls-files | grep -E "^strangler-lab/media/|^strangler-lab/logs/"
(no output)
git ls-files | grep -i facilitator
(no output)
git ls-files | grep -i verification
(no output before this commit — VERIFICATION.md ships as of this fix-pass commit)
```

| Check | Result |
|---|---|
| `FACILITATOR-PRIVATE.md` gitignored AND not tracked in history | **PASS** — in `.gitignore`, zero hits in `git ls-files` |
| `media/` and `logs/` gitignored, no generated files tracked | **PASS** — both in `.gitignore`, zero tracked paths under either |
| `.git` not bloated by committed seed images | **PASS** — 1016K total, 88 tracked files |
| `VERIFICATION.md` is tracked (ships with the repo) | **FAIL at start of this check, fixed by this commit** — it existed on disk but had never been `git add`ed; committed as part of this fix pass |
| Working tree committed and clean | **FAIL at start of this check, fixed by this commit** — same cause as above; clean after commit (see final `git status --porcelain` at the bottom of this report) |

**Verdict: PASS on 3/5 sub-checks as found; the other 2 were the same
root cause (this report itself was never `git add`ed after being
written) and are fixed by the commit that ships this update.**

### A7. Cold-clone smoke test — the most representative check in this report, never run before now

Cloned the repo into a fresh temporary directory with no prior images
or volumes, and followed `README.md` exactly as written — nothing else.

```
git clone <repo> /tmp/.../coldclone
cd coldclone/strangler-lab
docker compose -p coldclone up --build -d
```
```
Container coldclone-db-1     Started (healthy)
Container coldclone-web-1    Started
Container coldclone-nginx-1  Started
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/
200
```
**Up and reachable in ~13 seconds** from a cold `--build`.

```
docker compose -p coldclone exec web python manage.py seed_data
...
Done in 81.3s
```
**`seed_data` runs cleanly, ~82 seconds total**, exactly as the README
describes ("takes a couple of minutes, grab a coffee").

Storefront usability, checked end to end with nothing beyond
README-documented knowledge:
```
curl http://localhost:8000/                          → 200, product links present
curl http://localhost:8000/products/product-49999/    → 200
grep 'src="/media/' the product page                  → /media/products/product-49999.png
curl http://localhost:8000/media/products/product-49999.png  → 200
```
Homepage renders, a product detail page renders, and its image loads —
**product images render.**

Full checkout, logged in as a seeded user (`user1` / `password123`,
exactly as documented in the README's "Running it" section):
```
POST /accounts/login/         → 302 (logged in)
POST /cart/add/1/             → 302 (added to cart)
POST /orders/checkout/        → 200, "Order #200001 ... Order placed. Thanks for shopping with us!"
docker compose -p coldclone exec web cat /app/logs/orders.log | tail -1
2026-09-03T06:24:11+00:00 order=200001 user=2 total=234.58 status=paid txn=txn_c685ad647f2e4d2785ce
```
**Checkout is completable** — order created, payment approved, log
line written, matching the README's own description of the checkout
flow.

Every step above used only what `README.md` states (Docker, `docker
compose up`, `manage.py seed_data`, the seeded `admin`/`password123`
credentials, `localhost:8000`). Nothing required prior session
knowledge.

**Verdict: PASS.** The intern experience the README promises is real:
cold clone → `docker compose up --build` → `seed_data` →
usable storefront with rendering images and a completable checkout, no
undocumented steps required.

---

## Defects found

**All six defects below are now fixed** — see "Fixes applied" for what
changed in each case and the re-verification that proved it. Left the
original write-ups intact for context; each is now annotated.

1. **FIXED. `README.md` is missing from the repository entirely** (Part E).
   Not on disk, never committed to git. This is the single most severe
   finding in this audit — every intern-facing requirement about the
   README (handover tone, no anti-pattern spoilers, setup instructions)
   is moot because the file isn't there. Undermines the very first
   thing an intern does when they fork this repo. Root cause not
   determined by this audit (out of scope — this is a read-and-run
   verification pass, not a git forensics investigation); noted as fact
   only.

2. **FIXED. `seed_data`'s idempotency is row-count-based and cannot detect or
   repair lost media files** (A1). Because `/app/media` is intentionally
   unpersisted (correctly, per A2/anti-pattern #2), any container
   recreation after seeding silently leaves 50,000 `catalog_product.image`
   rows pointing at files that no longer exist, and re-running
   `seed_data` does not notice or fix this because it only checks
   `Product.objects.count() >= PRODUCT_COUNT`. Reproduced twice in this
   session, independently, both times via an ordinary `--force-recreate`.
   Undermines any training round that relies on product images actually
   rendering — an intern doing a normal "reset my environment" cycle
   will find every product image broken with no obvious explanation in
   the DB (rows look fine) unless they think to check the filesystem
   directly.

3. **NOT A DEFECT — INTENTIONAL, NOT CHANGED. Gunicorn runs a single worker process** (A3), which is a
   deliberate tradeoff (documented in `FACILITATOR-PRIVATE.md`) to keep
   the session-cache and scheduler anti-patterns clean at 1 replica —
   but it also means the report-endpoint-interference lesson (anti-pattern
   #5) is currently demonstrated at an artificially extreme magnitude
   (100x p95 blowup) that would probably look different, though still
   real, under a more typical multi-worker gunicorn configuration. Per
   this fix pass's explicit scope, `--workers 1 --threads 4` is kept
   exactly as-is; the reasoning and the consequence for C9's numbers are
   now documented in `FACILITATOR-PRIVATE.md` so a facilitator presents
   the ~100x figure as directionally real but not universally
   generalizable, instead of this being an undocumented gap.

4. **FIXED. No `restart:` policy in `docker-compose.yml`** means a crashed
   `web` container (Part B) stays dead indefinitely rather than being
   retried. Combined with the concurrent-migration race, this means
   `docker compose up --scale web=3` against an empty database has a
   real, reproducible chance of leaving the stack at 1/3 capacity with
   no automatic recovery — worse than what the same race would look
   like on the actual target platform (Kubernetes), where a Deployment's
   restart policy would likely paper over it. Facilitators relying on
   "just re-run `--scale web=3`, it's fine" should know this isn't
   guaranteed.

5. **FIXED. `docker compose restart web` does not demonstrate the "restart
   wipes state" story** (C8) the way most people would expect from the
   phrase "restart the container" — only actual recreation does. The
   original build's own self-verification checklist phrase ("Restart
   the web container, confirm `/app/logs/orders.log` is empty") is
   ambiguous and will not reproduce for anyone who reads it as `docker
   compose restart`. Worth rewording in any instructions given to
   interns.

6. **FIXED. Filling in `docs/BASELINE.md` (this audit's own Part D) conflicts
   with the file's stated purpose** as a blank pre-work template for
   interns. Resolved by moving the auditor's numbers to
   `docs/BASELINE-REFERENCE.md` and resetting `docs/BASELINE.md` to a
   blank template — see Part D and "Fixes applied."

## Fixes applied

| # | Defect (from above) | Fix | Re-verification |
|---|---|---|---|
| 1 | `README.md` missing entirely | Wrote `README.md` at the repo root as a matter-of-fact developer handover note: setup (`docker compose up`, `seed_data`, reachable at `localhost:8000`, admin credentials), a domain overview of the six Django apps, and a "Known issues" section with only trivial cosmetic items. Contains none of the flagged anti-pattern/scaling vocabulary. | Part E re-run: `grep -rniE "kubernetes\|k8s\|replica\|scal\|microservice\|helm\|pod\|argo\|strangler\|monolith" README.md` → no matches. A7's cold-clone test independently proved the README alone is sufficient to run the whole stack. |
| 2 | `seed_data` can't detect/repair lost media | Split `catalog/management/commands/seed_data.py`'s idempotency check: added a standalone `repair_missing_media()` step that checks each product's image file independently of the row-count check, and rewrites only the missing files (no DB writes) when the row check passes but files are gone. | A1 re-run: force-recreate wipes `/app/media` (0 files) while `catalog_product` rows stay at 50,000; re-running `seed_data` restores exactly 50,000 files, 198M, with every row count (users/products/orders/orderitems/payments) identical before and after. |
| 3 | Gunicorn single-worker tradeoff undocumented | No code change (explicitly out of scope — `--workers 1 --threads 4` must stay). Documented the reasoning and the C9 consequence in `FACILITATOR-PRIVATE.md`: the ~100x p95 blowup is amplified by the single-process GIL and should be presented as directionally real, not a universal number. | Confirmed present in `FACILITATOR-PRIVATE.md` (lines ~144-172, predates this pass — already committed in the initial commit). |
| 4 | No restart policy on `web` | Added `restart: on-failure` to the `web` service only in `docker-compose.yml`. | Part B re-run: `docker compose down -v && docker compose up --scale web=3` against an empty DB. Same race still crashes 2/3 containers (untouched, by design), but they now self-heal via one restart each, converging to 3/3 in ~22 seconds instead of staying dead indefinitely. |
| 5 | "Restart" ambiguity in docs | Replaced every "restart the container"-style instruction in `FACILITATOR-PRIVATE.md` with the explicit `docker compose up -d --force-recreate web` plus a note that plain `docker compose restart` will not reproduce the symptom. Not added to `README.md` (by design — that file stays uninformative about internals). | C8 re-run: plain `docker compose restart web` leaves `orders.log` untouched; `--force-recreate` empties it — same mechanism as the original audit, now correctly worded in the facilitator doc. |
| 6 | `docs/BASELINE.md` filled in, defeating its purpose | Moved the auditor's filled-in numbers to new `docs/BASELINE-REFERENCE.md` (same table shape, plus an environment note that these are the auditor's numbers, not a target). Reset `docs/BASELINE.md` to a blank template with fill-in-first instructions at the top. | Part D re-run: `docs/BASELINE.md` has zero populated value cells; `docs/BASELINE-REFERENCE.md` retains the original measurements for reference. |

Two gaps the original audit missed were also closed (no code fix
needed — verification only): **A5** (hardcoded config, anti-pattern #6,
never checked before — now PASS on every sub-check) and **A6**
(repository hygiene — found `VERIFICATION.md` itself had never been
`git add`ed; fixed by this commit). **A7** (cold-clone smoke test) was
run for the first time and passed cleanly against the fixed README with
no undocumented steps required.

**No fix introduced a new problem.** Every check listed as
RE-VERIFIED above passed on first re-run; the media-repair step
correctly no-ops when nothing is missing (confirmed in C2's re-run);
`restart: on-failure` had no effect on ordinary single-replica startup
(confirmed in C1's re-run).

---

## Not verifiable in this environment

- **Real multi-node / multi-VM behavior.** Everything here was tested
  with Docker Compose's `--scale` on a single Docker host — all
  "replicas" are containers sharing one kernel and one Docker daemon.
  Network-partition behavior, cross-node clock skew, or anything
  specific to a real Kubernetes cluster (the actual target platform)
  was not and could not be tested here.
- **Long-run stability.** All observations are from a session lasting
  under an hour of wall-clock container uptime. No data on what happens
  after days of uptime (e.g., `LocMemCache` memory growth, log file
  growth without rotation, connection pool behavior over time).
- **Behavior under real concurrent user load beyond k6's synthetic
  patterns.** The load tests here use k6's specific request patterns
  (fixed VU counts, no think-time randomization beyond `sleep(1)`);
  production-shaped traffic (bursty, heavy-tailed) was not simulated.
- **The original root cause of the missing `README.md`.** Confirmed it
  was absent from both the filesystem and git history at audit time;
  never investigated further (out of scope for a read-and-run
  verification pass) — the fix pass wrote a new one rather than
  attempting to recover a lost original.
- **Windows/macOS Docker Desktop behavior.** All testing was on native
  Linux Docker; resource-limit defaults and filesystem performance
  differ under Docker Desktop's VM layer and were not tested.
