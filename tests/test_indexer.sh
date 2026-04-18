#!/usr/bin/env bash
# Indexer endpoint tests — runs against the live container.
# Skipped entirely if the container, Redis, or embedding server are unavailable.

set -uo pipefail

BASE="${BIBLION_URL:-http://localhost:18765}"
PROJECT="_curl_test_indexer"
# Use the container-internal path to the bundled source so indexing always works
SOURCE_DIR="${INDEXER_SOURCE_DIR:-/app/indexer}"
PASS=0
FAIL=0

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; RESET='\033[0m'

pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; [[ -n "${2:-}" ]] && echo "      $2"; FAIL=$((FAIL + 1)); }

jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
jeq()  { [[ "$(echo "$1" | jget "$2")" == "$3" ]]; }

# ── prerequisites ─────────────────────────────────────────────────────────────
check_prerequisites() {
  echo "Checking prerequisites..."

  # 1. Container health
  if ! curl -sf "$BASE/health" > /dev/null 2>&1; then
    echo -e "${YELLOW}Container not reachable at $BASE — skipping all tests.${RESET}"
    exit 0
  fi

  # 2. Indexer status (covers Redis connectivity)
  STATUS=$(curl -sf "$BASE/indexer/status" 2>/dev/null)
  IDX_STATUS=$(echo "$STATUS" | jget "d['status']")
  if [[ "$IDX_STATUS" != "ok" ]]; then
    REASON=$(echo "$STATUS" | jget "d.get('reason','unknown')")
    echo -e "${YELLOW}Indexer not ready (reason: $REASON) — skipping all tests.${RESET}"
    exit 0
  fi

  # 3. Biblion ready (implies embedding server is reachable — required for indexer start/search)
  BIB_STATUS=$(curl -sf "$BASE/biblion/status" 2>/dev/null)
  BIB_TYPE=$(echo "$BIB_STATUS" | jget "d['type']")
  if [[ "$BIB_TYPE" != "ready" ]]; then
    echo -e "${YELLOW}Biblion not ready (embedding may be down) — skipping all tests.${RESET}"
    exit 0
  fi

  echo "  All prerequisites met."
  echo ""
}

# ── cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
  curl -sf -X DELETE "$BASE/indexer/clear" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"$PROJECT\"}" > /dev/null 2>&1 || true
}
trap cleanup EXIT

# ── tests ─────────────────────────────────────────────────────────────────────
test_status_ok() {
  echo "GET /indexer/status"
  R=$(curl -sf "$BASE/indexer/status")
  jeq "$R" "d['status']" "ok" \
    && pass "status=ok" \
    || fail "unexpected status" "$R"
  echo "$R" | jget "d['redis_url']" > /dev/null \
    && pass "redis_url present" \
    || fail "redis_url missing"
  echo "$R" | jget "isinstance(d['projects'], list)" | grep -q "True" \
    && pass "projects is a list" \
    || fail "projects field missing or wrong type"
}

test_start_indexing() {
  echo "POST /indexer/start (source_dir=$SOURCE_DIR)"
  R=$(curl -sf -X POST "$BASE/indexer/start" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"$PROJECT\",\"source_dir\":\"$SOURCE_DIR\"}")
  jeq "$R" "d['project_id']" "$PROJECT" \
    && pass "project_id echoed" \
    || fail "wrong project_id in response" "$R"
  INDEXED=$(echo "$R" | jget "d['indexed']")
  [[ "$INDEXED" -gt 0 ]] \
    && pass "indexed $INDEXED chunk(s)" \
    || fail "nothing indexed (check SOURCE_DIR=$SOURCE_DIR is readable inside container)" "$R"
  ERRORS=$(echo "$R" | jget "len(d['errors'])")
  [[ "$ERRORS" -eq 0 ]] \
    && pass "no errors" \
    || fail "$ERRORS error(s) during indexing" "$R"
}

test_status_shows_project() {
  echo "GET /indexer/status (after indexing)"
  R=$(curl -sf "$BASE/indexer/status")
  HAS=$(echo "$R" | jget "'$PROJECT' in d['projects']")
  [[ "$HAS" == "True" ]] \
    && pass "project '$PROJECT' listed" \
    || fail "project not found in status" "$R"
}

test_start_idempotent() {
  echo "POST /indexer/start (re-index same dir — all skipped)"
  R=$(curl -sf -X POST "$BASE/indexer/start" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"$PROJECT\",\"source_dir\":\"$SOURCE_DIR\"}")
  INDEXED=$(echo "$R" | jget "d['indexed']")
  SKIPPED=$(echo "$R" | jget "d['skipped']")
  [[ "$INDEXED" -eq 0 ]] \
    && pass "nothing re-indexed (all up to date)" \
    || fail "unexpected re-indexing of $INDEXED chunk(s)" "$R"
  [[ "$SKIPPED" -gt 0 ]] \
    && pass "$SKIPPED file(s) skipped as unchanged" \
    || fail "expected skipped > 0" "$R"
}

test_search() {
  echo "POST /indexer/search"
  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"redis storage index\",\"project_id\":\"$PROJECT\"}")
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -ge 1 ]] \
    && pass "search returned $COUNT result(s)" \
    || fail "search returned no results (score may be below threshold)" "$R"
  if [[ "$COUNT" -ge 1 ]]; then
    echo "$R" | jget "d['results'][0]['file_path']" > /dev/null \
      && pass "file_path present" \
      || fail "file_path missing in result"
    echo "$R" | jget "d['results'][0]['score']" > /dev/null \
      && pass "score present" \
      || fail "score missing in result"
    echo "$R" | jget "d['results'][0]['start_line']" > /dev/null \
      && pass "start_line present" \
      || fail "start_line missing in result"
    echo "$R" | jget "d['results'][0]['text']" > /dev/null \
      && pass "text present" \
      || fail "text missing in result"
  fi
}

test_search_custom_top_k() {
  echo "POST /indexer/search (top_k=1)"
  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"redis\",\"project_id\":\"$PROJECT\",\"top_k\":1}")
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -le 1 ]] \
    && pass "top_k=1 respected (got $COUNT)" \
    || fail "too many results for top_k=1 ($COUNT)"
}

test_search_unknown_project() {
  echo "POST /indexer/search (unknown project)"
  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d '{"query":"anything","project_id":"_no_such_project_"}')
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -eq 0 ]] \
    && pass "empty results for unknown project" \
    || fail "unexpected results for unknown project ($COUNT)"
}

test_clear() {
  echo "DELETE /indexer/clear"
  R=$(curl -sf -X DELETE "$BASE/indexer/clear" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"$PROJECT\"}")
  jeq "$R" "d['project_id']" "$PROJECT" \
    && pass "project_id echoed" \
    || fail "wrong project_id in response" "$R"
  DELETED=$(echo "$R" | jget "d['deleted']")
  [[ "$DELETED" -gt 0 ]] \
    && pass "deleted $DELETED key(s)" \
    || fail "nothing deleted" "$R"

  # Confirm project is gone from status
  R2=$(curl -sf "$BASE/indexer/status")
  STILL=$(echo "$R2" | jget "'$PROJECT' in d['projects']")
  [[ "$STILL" == "False" ]] \
    && pass "project removed from status after clear" \
    || fail "project still listed after clear"
}

# ── run ───────────────────────────────────────────────────────────────────────
echo "========================================"
echo " Indexer endpoint tests"
echo "========================================"
check_prerequisites

test_status_ok;           echo ""
test_start_indexing;      echo ""
test_status_shows_project; echo ""
test_start_idempotent;    echo ""
test_search;              echo ""
test_search_custom_top_k; echo ""
test_search_unknown_project; echo ""
test_clear;               echo ""

echo "========================================"
echo -e " ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}"
echo "========================================"
[[ "$FAIL" -eq 0 ]]
