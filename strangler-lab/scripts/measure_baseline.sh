#!/usr/bin/env bash
#
# Measures the numbers docs/BASELINE.md asks for, on this machine, against
# a freshly seeded single-replica stack. Writes machine-readable results to
# /tmp/baseline_results.env for the caller to fold into BASELINE.md.
#
# Order of operations matters: cold start is measured against a truly empty
# database (docker compose down -v), then seed_data is timed, then endpoint
# latency and DB-size/dump/restore are measured against that freshly seeded
# data - so every number in one run comes from a single consistent dataset.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

BASE="http://localhost:8000"
DC="docker compose"
RESULTS=/tmp/baseline_results.env
COOKIE_JAR=$(mktemp)
LOGIN_USER="user1"
LOGIN_PASS="password123"

: > "$RESULTS"
put() { echo "$1=$2" >> "$RESULTS"; echo "  $1 = $2"; }

echo "== 0. tear down and drop volumes for a true cold start =="
$DC down -v

echo "== 1. cold start: docker compose up -d -> first 200 =="
UP_START=$(date +%s.%N)
$DC up -d
poll_200() {
    local url="$1"
    while true; do
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 "$url" 2>/dev/null || echo "000")
        if [ "$code" = "200" ]; then
            date +%s.%N
            return
        fi
        sleep 0.2
    done
}
HEALTH_200_AT=$(poll_200 "$BASE/health/")
COLD_HEALTH_S=$(echo "$HEALTH_200_AT $UP_START" | awk '{printf "%.2f", $1-$2}')
put COLD_HEALTH_S "$COLD_HEALTH_S"

HOME_200_AT=$(poll_200 "$BASE/")
COLD_HOME_S=$(echo "$HOME_200_AT $UP_START" | awk '{printf "%.2f", $1-$2}')
put COLD_HOME_S "$COLD_HOME_S"

echo "== 2. seed_data timing (empty DB from step 0) =="
SEED_START=$(date +%s.%N)
$DC exec -T web python manage.py seed_data
SEED_END=$(date +%s.%N)
SEED_DURATION_S=$(echo "$SEED_END $SEED_START" | awk '{printf "%.1f", $1-$2}')
put SEED_DURATION_S "$SEED_DURATION_S"

psql_val() { $DC exec -T db psql -U storefront storefront -tAc "$1" | tr -d '\r' | tr -d ' '; }
put ROW_USERS "$(psql_val 'select count(*) from auth_user;')"
put ROW_PRODUCTS "$(psql_val 'select count(*) from catalog_product;')"
put ROW_ORDERS "$(psql_val 'select count(*) from orders_order;')"
put ROW_ORDERITEMS "$(psql_val 'select count(*) from orders_orderitem;')"
put ROW_PAYMENTS "$(psql_val 'select count(*) from payments_payment;')"

echo "== 3. warm up =="
for i in $(seq 1 8); do
    curl -s -o /dev/null "$BASE/" &
    curl -s -o /dev/null "$BASE/products/" &
done
wait
SLUG=$(psql_val "select slug from catalog_product order by id limit 1;")
for i in $(seq 1 8); do
    curl -s -o /dev/null "$BASE/products/$SLUG/" &
done
wait

# --- percentile helper: nearest-rank on a sorted ms-times file --------------
# echoes "p50 p95 p99" (p99 as "n/a" when the sample size makes it equal max)
percentiles() {
    local file="$1"
    local n
    n=$(wc -l < "$file")
    if [ "$n" -eq 0 ]; then echo "n/a n/a n/a"; return; fi
    sort -n "$file" -o "$file"
    idx() { local p=$1; local i=$(( (p * n + 99) / 100 )); [ "$i" -lt 1 ] && i=1; [ "$i" -gt "$n" ] && i=$n; echo "$i"; }
    local i50 i95 i99
    i50=$(idx 50); i95=$(idx 95); i99=$(idx 99)
    local p50 p95 p99
    p50=$(sed -n "${i50}p" "$file")
    p95=$(sed -n "${i95}p" "$file")
    if [ "$i99" -eq "$n" ]; then p99="n/a"; else p99=$(sed -n "${i99}p" "$file"); fi
    echo "$p50 $p95 $p99"
}

# --- GET benchmark: N samples, verifies status==200, records time_total*1000 ms
# optional $4 = cookie jar path, to benchmark an authenticated endpoint
bench_get() {
    local name="$1" url="$2" n="$3" jar="${4:-}"
    local tmp; tmp=$(mktemp)
    local errors=0
    local jar_args=()
    [ -n "$jar" ] && jar_args=(-b "$jar")
    for i in $(seq 1 "$n"); do
        out=$(curl -s "${jar_args[@]}" -o /dev/null -w "%{http_code} %{time_total}" --max-time 30 "$url")
        code=$(echo "$out" | awk '{print $1}')
        t=$(echo "$out" | awk '{print $2}')
        if [ "$code" = "200" ]; then
            awk -v t="$t" 'BEGIN{printf "%.2f\n", t*1000}' >> "$tmp"
        else
            errors=$((errors+1))
        fi
    done
    read -r p50 p95 p99 <<< "$(percentiles "$tmp")"
    local ok=$((n-errors))
    put "${name}_N" "$n"
    put "${name}_OK" "$ok"
    put "${name}_ERR" "$errors"
    put "${name}_P50" "$p50"
    put "${name}_P95" "$p95"
    put "${name}_P99" "$p99"
    rm -f "$tmp"
}

echo "== 4. GET endpoint latency (unauthenticated) =="
bench_get HOME "$BASE/" 60
bench_get LIST "$BASE/products/" 60
bench_get DETAIL "$BASE/products/$SLUG/" 60

echo "== 5. log in for cart-add / checkout / report (report requires auth) =="
rm -f "$COOKIE_JAR"
curl -s -c "$COOKIE_JAR" -o /dev/null "$BASE/accounts/login/"
CSRF=$(awk '$6=="csrftoken"{print $7}' "$COOKIE_JAR")
curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null -w "%{http_code}" \
    -H "Referer: $BASE/accounts/login/" \
    -d "username=$LOGIN_USER&password=$LOGIN_PASS&csrfmiddlewaretoken=$CSRF" \
    "$BASE/accounts/login/" > /tmp/login_code
LOGIN_CODE=$(cat /tmp/login_code)
if [ "$LOGIN_CODE" != "302" ]; then
    echo "LOGIN FAILED (http $LOGIN_CODE) - aborting cart/checkout measurements" >&2
    put LOGIN_OK "no"
else
    put LOGIN_OK "yes"
    CSRF=$(awk '$6=="csrftoken"{print $7}' "$COOKIE_JAR")

    echo "== 5b. report endpoint (authenticated, 5 samples) =="
    bench_get REPORT "$BASE/reports/sales/" 5 "$COOKIE_JAR"

    echo "== 6. product pool with real stock for cart-add / checkout =="
    mapfile -t PIDS < <($DC exec -T db psql -U storefront storefront -tAc \
        "select id from catalog_product where stock - reserved_stock >= 10 order by id limit 100;" | tr -d '\r')

    echo "== 7. cart add: 60 samples, one distinct product per sample =="
    tmp=$(mktemp); errors=0; n=60
    for i in $(seq 0 $((n-1))); do
        pid=${PIDS[$((i % ${#PIDS[@]}))]}
        out=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null -w "%{http_code} %{time_total}" \
            -H "Referer: $BASE/products/$SLUG/" \
            -d "quantity=1&csrfmiddlewaretoken=$CSRF" \
            "$BASE/cart/add/$pid/")
        code=$(echo "$out" | awk '{print $1}'); t=$(echo "$out" | awk '{print $2}')
        if [ "$code" = "302" ] || [ "$code" = "200" ]; then
            awk -v t="$t" 'BEGIN{printf "%.2f\n", t*1000}' >> "$tmp"
        else
            errors=$((errors+1))
        fi
    done
    read -r p50 p95 p99 <<< "$(percentiles "$tmp")"
    put CARTADD_N "$n"; put CARTADD_OK "$((n-errors))"; put CARTADD_ERR "$errors"
    put CARTADD_P50 "$p50"; put CARTADD_P95 "$p95"; put CARTADD_P99 "$p99"
    rm -f "$tmp"

    echo "== 8. checkout: 20 samples, add-then-checkout, only checkout POST timed =="
    tmp=$(mktemp); errors=0; n=20
    for i in $(seq 0 $((n-1))); do
        pid=${PIDS[$(((i + 60) % ${#PIDS[@]}))]}
        curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null \
            -H "Referer: $BASE/products/$SLUG/" \
            -d "quantity=1&csrfmiddlewaretoken=$CSRF" \
            "$BASE/cart/add/$pid/" > /dev/null
        out=$(curl -s -b "$COOKIE_JAR" -c "$COOKIE_JAR" -o /dev/null -w "%{http_code} %{time_total}" \
            -H "Referer: $BASE/orders/checkout/" \
            -d "shipping_address=1 Baseline St&payment_method=card&csrfmiddlewaretoken=$CSRF" \
            "$BASE/orders/checkout/")
        code=$(echo "$out" | awk '{print $1}'); t=$(echo "$out" | awk '{print $2}')
        if [ "$code" = "302" ] || [ "$code" = "200" ]; then
            awk -v t="$t" 'BEGIN{printf "%.2f\n", t*1000}' >> "$tmp"
        else
            errors=$((errors+1))
        fi
    done
    read -r p50 p95 p99 <<< "$(percentiles "$tmp")"
    put CHECKOUT_N "$n"; put CHECKOUT_OK "$((n-errors))"; put CHECKOUT_ERR "$errors"
    put CHECKOUT_P50 "$p50"; put CHECKOUT_P95 "$p95"; put CHECKOUT_P99 "$p99"
    rm -f "$tmp"
fi

echo "== 9. database size on disk =="
DB_SIZE_BYTES=$(psql_val "select pg_database_size('storefront');")
DB_SIZE_PRETTY=$(psql_val "select pg_size_pretty(pg_database_size('storefront'));")
put DB_SIZE_BYTES "$DB_SIZE_BYTES"
put DB_SIZE_PRETTY "$DB_SIZE_PRETTY"

echo "== 10. pg_dump =="
DUMP_START=$(date +%s.%N)
$DC exec -T db pg_dump -U storefront -Fc storefront -f /tmp/baseline.dump
DUMP_END=$(date +%s.%N)
DUMP_DURATION_S=$(echo "$DUMP_END $DUMP_START" | awk '{printf "%.2f", $1-$2}')
DUMP_SIZE_BYTES=$($DC exec -T db stat -c%s /tmp/baseline.dump | tr -d '\r')
DUMP_SIZE_PRETTY=$(numfmt --to=iec --suffix=B "$DUMP_SIZE_BYTES" 2>/dev/null || echo "${DUMP_SIZE_BYTES}B")
put DUMP_DURATION_S "$DUMP_DURATION_S"
put DUMP_SIZE_BYTES "$DUMP_SIZE_BYTES"
put DUMP_SIZE_PRETTY "$DUMP_SIZE_PRETTY"

echo "== 11. pg_restore into a fresh empty database =="
$DC exec -T db psql -U storefront postgres -c "DROP DATABASE IF EXISTS baseline_restore_test;" > /dev/null
$DC exec -T db psql -U storefront postgres -c "CREATE DATABASE baseline_restore_test OWNER storefront;" > /dev/null
RESTORE_START=$(date +%s.%N)
$DC exec -T db pg_restore -U storefront -d baseline_restore_test /tmp/baseline.dump
RESTORE_END=$(date +%s.%N)
RESTORE_DURATION_S=$(echo "$RESTORE_END $RESTORE_START" | awk '{printf "%.2f", $1-$2}')
put RESTORE_DURATION_S "$RESTORE_DURATION_S"
$DC exec -T db psql -U storefront postgres -c "DROP DATABASE baseline_restore_test;" > /dev/null
$DC exec -T db rm -f /tmp/baseline.dump

echo "== 12. environment =="
put ENV_DATE "$(date -u +%Y-%m-%d)"
put ENV_COMMIT "$(git rev-parse --short HEAD)"
put ENV_CPU "$(nproc)"
put ENV_RAM "$(free -h | awk '/^Mem:/{print $2}')"
put ENV_COMPOSE_VERSION "$($DC version --short 2>/dev/null || $DC version)"

rm -f "$COOKIE_JAR"
echo "== done. results in $RESULTS =="
