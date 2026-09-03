#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# CONFIG
# ============================================================

BASE="http://localhost:8000"

N=60
WARMUP=8

PRODUCT_SLUG="product-49999"

# Django login bilgileri
LOGIN_USERNAME="user1"
LOGIN_PASSWORD="password123"

LOGIN_URL="$BASE/accounts/login/"
REPORT_URL="$BASE/reports/sales/"

OUTPUT="benchmark_$(date +'%Y%m%d_%H%M%S').txt"

COOKIE_JAR=""
CSRF_TOKEN=""


# ============================================================
# LOG
# ============================================================

log() {
  echo "$*" | tee -a "$OUTPUT"
}


# ============================================================
# CLEANUP
# ============================================================

cleanup() {
  if [[ -n "${COOKIE_JAR:-}" && -f "$COOKIE_JAR" ]]; then
    rm -f "$COOKIE_JAR"
  fi
}

trap cleanup EXIT


# ============================================================
# DATABASE SEED CHECK
# ============================================================

check_seed() {
  log "========================================"
  log "DATABASE SEED CHECK"
  log "========================================"

  local product_count
  local order_count

  product_count=$(
    docker compose exec -T db \
      psql -U storefront storefront \
      -tAc "SELECT count(*) FROM catalog_product;" \
      2>/dev/null || echo "ERROR"
  )

  if [[ "$product_count" == "ERROR" ]]; then
    log "WARNING: Product count kontrol edilemedi."
  else
    product_count=$(echo "$product_count" | xargs)

    log "catalog_product count: $product_count"

    if [[ "$product_count" != "50000" ]]; then
      log ""
      log "WARNING!"
      log "Beklenen ürün sayısı : 50000"
      log "Bulunan ürün sayısı  : $product_count"
      log ""
      log "Catalog benchmark sonuçları referans baseline ile"
      log "doğrudan karşılaştırılmamalı."
    else
      log "Product dataset OK."
    fi
  fi

  log ""

  order_count=$(
    docker compose exec -T db \
      psql -U storefront storefront \
      -tAc "SELECT count(*) FROM orders_order;" \
      2>/dev/null || echo "UNKNOWN"
  )

  if [[ "$order_count" != "UNKNOWN" ]]; then
    order_count=$(echo "$order_count" | xargs)

    log "orders_order count: $order_count"

    if [[ "$order_count" != "200000" ]]; then
      log "WARNING: Beklenen sipariş sayısı yaklaşık 200000."
    else
      log "Order dataset OK."
    fi
  else
    log "Order count kontrolü atlandı."
    log "order_sales tablosu bulunamadı veya tablo adı farklı."
  fi

  log ""
}


# ============================================================
# PERCENTILE / RESULT CALCULATION
# ============================================================

calculate_results() {
  local label="$1"
  local tmp="$2"
  local failures="$3"

  local success_count

  success_count=$(wc -l < "$tmp" | xargs)

  log ""
  log "Successful requests : $success_count"
  log "Failed requests     : $failures"

  if [[ "$success_count" -eq 0 ]]; then
    log "ERROR: Ölçülebilecek başarılı request yok."
    log ""
    return 1
  fi

  sort -n "$tmp" | awk \
    -v label="$label" \
    -v failures="$failures" '

    {
      t[NR] = $1 * 1000
      sum += t[NR]
    }

    function ceil(x) {
      return (x == int(x)) ? x : int(x) + 1
    }

    END {

      n = NR

      p50_idx = ceil(0.50 * n)
      p95_idx = ceil(0.95 * n)
      p99_idx = ceil(0.99 * n)

      avg = sum / n

      p50 = sprintf("%.2f ms", t[p50_idx])

      if (p95_idx >= n)
        p95 = "n/a"
      else
        p95 = sprintf("%.2f ms", t[p95_idx])

      if (p99_idx >= n)
        p99 = "n/a"
      else
        p99 = sprintf("%.2f ms", t[p99_idx])


      printf "\nRESULT\n"
      printf "----------------------------------------\n"

      printf "%-18s %s\n", "endpoint:", label
      printf "%-18s %d\n", "samples:", n
      printf "%-18s %d\n", "failed:", failures

      printf "%-18s %.2f ms\n", "avg:", avg
      printf "%-18s %.2f ms\n", "min:", t[1]
      printf "%-18s %s\n", "p50:", p50
      printf "%-18s %s\n", "p95:", p95
      printf "%-18s %s\n", "p99:", p99
      printf "%-18s %.2f ms\n", "max:", t[n]

      printf "\nNearest-rank indexes\n"

      printf "p50 = %d/%d\n", p50_idx, n
      printf "p95 = %d/%d\n", p95_idx, n
      printf "p99 = %d/%d\n", p99_idx, n

      if (p95_idx >= n)
        printf "NOTE: p95 == max observation -> n/a olarak raporlandı.\n"

      if (p99_idx >= n)
        printf "NOTE: p99 == max observation -> n/a olarak raporlandı.\n"
    }

  ' | tee -a "$OUTPUT"

  log ""
}


# ============================================================
# NORMAL GET BENCHMARK
# ============================================================

measure() {
  local label="$1"
  local url="$2"
  local n="${3:-$N}"

  local tmp
  local failures=0

  tmp=$(mktemp)

  log "========================================"
  log "Endpoint : $label"
  log "URL      : $url"
  log "Requests : $n"
  log "Warmup   : $WARMUP"
  log "========================================"


  # ----------------------------------------------------------
  # PREFLIGHT
  # ----------------------------------------------------------

  local preflight_code

  preflight_code=$(
    curl \
      -s \
      -o /dev/null \
      -w '%{http_code}' \
      "$url"
  )

  if [[ "$preflight_code" != "200" ]]; then
    log "ERROR: Endpoint HTTP $preflight_code döndü."
    log "Benchmark ATLANDI."
    log ""

    rm -f "$tmp"
    return
  fi

  log "Preflight: HTTP 200 OK"


  # ----------------------------------------------------------
  # WARMUP
  # ----------------------------------------------------------

  log "Warmup başlıyor..."

  for _ in $(seq "$WARMUP"); do

    local warmup_code

    warmup_code=$(
      curl \
        -s \
        -o /dev/null \
        -w '%{http_code}' \
        "$url"
    )

    if [[ "$warmup_code" != "200" ]]; then
      log "WARNING: Warmup sırasında HTTP $warmup_code"
    fi

  done

  log "Warmup tamamlandı."


  # ----------------------------------------------------------
  # MEASURE
  # ----------------------------------------------------------

  log "Ölçüm başlıyor..."

  for _ in $(seq "$n"); do

    local result
    local code
    local duration

    result=$(
      curl \
        -s \
        -o /dev/null \
        -w '%{http_code} %{time_total}' \
        "$url"
    )

    code=$(awk '{print $1}' <<< "$result")
    duration=$(awk '{print $2}' <<< "$result")

    if [[ "$code" == "200" ]]; then

      echo "$duration" >> "$tmp"

    else

      ((failures += 1))

      log "WARNING: HTTP $code response ölçümden çıkarıldı."

    fi

  done


  # ----------------------------------------------------------
  # RESULT
  # ----------------------------------------------------------

  calculate_results "$label" "$tmp" "$failures"

  rm -f "$tmp"
}


# ============================================================
# DJANGO LOGIN
# ============================================================

django_login() {
  log "========================================"
  log "DJANGO LOGIN"
  log "========================================"

  COOKIE_JAR=$(mktemp)

  local login_html

  # ----------------------------------------------------------
  # Login sayfasını aç.
  # csrftoken cookie'si + form token alınır.
  # ----------------------------------------------------------

  login_html=$(
    curl \
      -s \
      -c "$COOKIE_JAR" \
      "$LOGIN_URL"
  )

  CSRF_TOKEN=$(
    echo "$login_html" |
      grep -oP 'name=["'"'"']csrfmiddlewaretoken["'"'"'][^>]*value=["'"'"']\K[^"'"'"']+' |
      head -n 1 || true
  )

  if [[ -z "$CSRF_TOKEN" ]]; then
    log "ERROR: CSRF token login formundan alınamadı."
    log "Login işlemi başarısız."
    log ""
    return 1
  fi

  log "CSRF token alındı."


  # ----------------------------------------------------------
  # Login POST
  # ----------------------------------------------------------

  local login_result
  local login_code
  local login_redirect

  login_result=$(
    curl \
      -s \
      -c "$COOKIE_JAR" \
      -b "$COOKIE_JAR" \
      -o /dev/null \
      -w '%{http_code} %{redirect_url}' \
      -X POST \
      --data-urlencode "username=$LOGIN_USERNAME" \
      --data-urlencode "password=$LOGIN_PASSWORD" \
      --data-urlencode "csrfmiddlewaretoken=$CSRF_TOKEN" \
      -H "Referer: $LOGIN_URL" \
      "$LOGIN_URL"
  )

  login_code=$(awk '{print $1}' <<< "$login_result")
  login_redirect=$(cut -d' ' -f2- <<< "$login_result")


  # Django başarılı login sonrası normalde 302 döndürür.
  if [[ "$login_code" != "302" && "$login_code" != "303" ]]; then
    log "ERROR: Login beklenen redirect'i döndürmedi."
    log "HTTP: $login_code"
    log "Benchmark report kısmı çalıştırılmayacak."
    log ""
    return 1
  fi

  log "Login response: HTTP $login_code"

  if [[ -n "$login_redirect" ]]; then
    log "Login redirect: $login_redirect"
  fi


  # ----------------------------------------------------------
  # Session gerçekten oluşmuş mu?
  # Report endpoint'i ile doğrula.
  # ----------------------------------------------------------

  local verify_result
  local verify_code
  local verify_redirect

  verify_result=$(
    curl \
      -s \
      -b "$COOKIE_JAR" \
      -o /dev/null \
      -w '%{http_code} %{redirect_url}' \
      "$REPORT_URL"
  )

  verify_code=$(awk '{print $1}' <<< "$verify_result")
  verify_redirect=$(cut -d' ' -f2- <<< "$verify_result")


  if [[ "$verify_code" != "200" ]]; then

    log "ERROR: Login sonrası report endpoint HTTP $verify_code döndü."

    if [[ -n "$verify_redirect" ]]; then
      log "Redirect: $verify_redirect"
    fi

    log ""
    log "Muhtemel sebepler:"
    log "- username/password yanlış"
    log "- kullanıcı report yetkisine sahip değil"
    log "- login form field isimleri farklı"
    log ""

    return 1
  fi

  log "Authenticated session OK."
  log "Report preflight: HTTP 200 OK"
  log ""
}


# ============================================================
# AUTHENTICATED BENCHMARK
# ============================================================

measure_authenticated() {
  local label="$1"
  local url="$2"
  local n="${3:-5}"

  local tmp
  local failures=0

  tmp=$(mktemp)

  log "========================================"
  log "Endpoint : $label"
  log "URL      : $url"
  log "Requests : $n"
  log "Auth     : Django session"
  log "Warmup   : $WARMUP"
  log "========================================"


  # ----------------------------------------------------------
  # PREFLIGHT
  # ----------------------------------------------------------

  local preflight_result
  local preflight_code
  local preflight_redirect

  preflight_result=$(
    curl \
      -s \
      -b "$COOKIE_JAR" \
      -o /dev/null \
      -w '%{http_code} %{redirect_url}' \
      "$url"
  )

  preflight_code=$(awk '{print $1}' <<< "$preflight_result")
  preflight_redirect=$(cut -d' ' -f2- <<< "$preflight_result")

  if [[ "$preflight_code" != "200" ]]; then

    log "ERROR: Authenticated endpoint HTTP $preflight_code döndü."

    if [[ -n "$preflight_redirect" ]]; then
      log "Redirect: $preflight_redirect"
    fi

    log "Benchmark ATLANDI."
    log ""

    rm -f "$tmp"
    return
  fi

  log "Preflight: HTTP 200 OK"


  # ----------------------------------------------------------
  # WARMUP
  # ----------------------------------------------------------
  #
  # Report yaklaşık 9 saniyeyse 8 warmup gereksiz yere
  # çok uzun sürebilir.
  #
  # Bu yüzden authenticated / report tarafında
  # maksimum 2 warmup kullanıyoruz.
  # ----------------------------------------------------------

  local auth_warmup="$WARMUP"

  if [[ "$auth_warmup" -gt 2 ]]; then
    auth_warmup=2
  fi

  log "Warmup başlıyor ($auth_warmup request)..."

  for _ in $(seq "$auth_warmup"); do

    local warmup_code

    warmup_code=$(
      curl \
        -s \
        -b "$COOKIE_JAR" \
        -o /dev/null \
        -w '%{http_code}' \
        "$url"
    )

    if [[ "$warmup_code" != "200" ]]; then
      log "WARNING: Warmup sırasında HTTP $warmup_code"
    fi

  done

  log "Warmup tamamlandı."


  # ----------------------------------------------------------
  # MEASURE
  # ----------------------------------------------------------

  log "Ölçüm başlıyor..."

  for _ in $(seq "$n"); do

    local result
    local code
    local duration

    result=$(
      curl \
        -s \
        -b "$COOKIE_JAR" \
        -o /dev/null \
        -w '%{http_code} %{time_total}' \
        "$url"
    )

    code=$(awk '{print $1}' <<< "$result")
    duration=$(awk '{print $2}' <<< "$result")

    if [[ "$code" == "200" ]]; then

      echo "$duration" >> "$tmp"

    else

      ((failures += 1))

      log "WARNING: HTTP $code response ölçümden çıkarıldı."

    fi

  done


  # ----------------------------------------------------------
  # RESULT
  # ----------------------------------------------------------

  calculate_results "$label" "$tmp" "$failures"

  rm -f "$tmp"
}


# ============================================================
# START
# ============================================================

echo "Benchmark started: $(date)" > "$OUTPUT"

log "Benchmark output: $OUTPUT"
log ""

check_seed


# ============================================================
# PUBLIC GET ENDPOINTS
# ============================================================

measure \
  "home" \
  "$BASE/" \
  60


measure \
  "catalog_list" \
  "$BASE/products/" \
  60


measure \
  "product_detail" \
  "$BASE/products/$PRODUCT_SLUG/" \
  60


# ============================================================
# AUTHENTICATED REPORT
# ============================================================

if django_login; then

  measure_authenticated \
    "report" \
    "$REPORT_URL" \
    5

else

  log "WARNING: Report benchmark login başarısız olduğu için atlandı."
  log ""

fi


# ============================================================
# FINISH
# ============================================================

log "========================================"
log "Benchmark finished: $(date)"
log "Results saved to: $OUTPUT"
log "========================================"