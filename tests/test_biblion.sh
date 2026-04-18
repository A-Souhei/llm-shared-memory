#!/usr/bin/env bash
# Biblion endpoint tests — runs against the live container.
# Skipped entirely if the container, Redis, or embedding server are unavailable.

set -uo pipefail

BASE="${BIBLION_URL:-http://localhost:18765}"
PROJECT="_curl_test"
PASS=0
FAIL=0
ENTRY_ID=""

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; RESET='\033[0m'

pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; [[ -n "${2:-}" ]] && echo "      $2"; FAIL=$((FAIL + 1)); }
skip() { echo -e "  ${YELLOW}⊘${RESET} $1 — skipped"; }

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

  # 2. Biblion service status (covers Redis connectivity)
  STATUS=$(curl -sf "$BASE/biblion/status" 2>/dev/null)
  TYPE=$(echo "$STATUS" | jget "d['type']")
  if [[ "$TYPE" != "ready" ]]; then
    REASON=$(echo "$STATUS" | jget "d.get('reason','unknown')")
    echo -e "${YELLOW}Biblion not ready (reason: $REASON) — skipping all tests.${RESET}"
    exit 0
  fi

  # biblion status=ready implies Redis + embedding were both reachable at startup

  echo "  All prerequisites met."
  echo ""
}

# ── cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
  curl -sf -X DELETE "$BASE/biblion/clear?project_id=$PROJECT" > /dev/null 2>&1 || true
}
trap cleanup EXIT

# ── tests ─────────────────────────────────────────────────────────────────────
test_health() {
  echo "GET /health"
  R=$(curl -sf "$BASE/health")
  jeq "$R" "d['status']" "ok" \
    && pass "returns {status: ok}" \
    || fail "unexpected response" "$R"
}

test_status_ready() {
  echo "GET /biblion/status"
  R=$(curl -sf "$BASE/biblion/status")
  jeq "$R" "d['type']" "ready" \
    && pass "type=ready" \
    || fail "not ready" "$R"
  echo "$R" | jget "d['redis_url']" > /dev/null \
    && pass "redis_url present" \
    || fail "redis_url missing"
  echo "$R" | jget "d['entry_count']" > /dev/null \
    && pass "entry_count present" \
    || fail "entry_count missing"
}

test_write() {
  echo "POST /biblion/write"
  R=$(curl -sf -X POST "$BASE/biblion/write" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"pattern\",\"content\":\"Use dependency injection for testability in Python\",\"tags\":[\"pattern\",\"testing\"],\"project_id\":\"$PROJECT\"}")
  jeq "$R" "d['success']" "True" \
    && pass "success=true" \
    || fail "write failed" "$R"
  ENTRY_ID=$(echo "$R" | jget "d['id']")
  [[ -n "$ENTRY_ID" ]] \
    && pass "id returned: $ENTRY_ID" \
    || fail "no id in response"
}

test_write_dedup() {
  echo "POST /biblion/write (dedup)"
  R=$(curl -sf -X POST "$BASE/biblion/write" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"pattern\",\"content\":\"Use dependency injection for testability in Python\",\"tags\":[\"pattern\"],\"project_id\":\"$PROJECT\"}")
  jeq "$R" "d['success']" "False" \
    && pass "duplicate detected (success=false)" \
    || fail "dedup not triggered" "$R"
  [[ "$(echo "$R" | jget "d['reason']")" == "duplicate" ]] \
    && pass "reason=duplicate" \
    || fail "reason mismatch" "$R"
}

test_list() {
  echo "GET /biblion/list"
  R=$(curl -sf "$BASE/biblion/list")
  COUNT=$(echo "$R" | jget "len(d)")
  [[ "$COUNT" -ge 1 ]] \
    && pass "at least 1 entry returned ($COUNT)" \
    || fail "empty list" "$R"
}

test_list_project_filter() {
  echo "GET /biblion/list?project_id=$PROJECT"
  R=$(curl -sf "$BASE/biblion/list?project_id=$PROJECT")
  COUNT=$(echo "$R" | jget "len(d)")
  [[ "$COUNT" -ge 1 ]] \
    && pass "filtered list returned $COUNT entry/ies" \
    || fail "no entries for project $PROJECT" "$R"
  PID=$(echo "$R" | jget "d[0]['project_id']")
  [[ "$PID" == "$PROJECT" ]] \
    && pass "project_id matches filter" \
    || fail "wrong project_id: $PID"
}

test_list_type_filter() {
  echo "GET /biblion/list?type=pattern"
  R=$(curl -sf "$BASE/biblion/list?type=pattern")
  ALL_MATCH=$(echo "$R" | jget "all(e['type']=='pattern' for e in d)")
  [[ "$ALL_MATCH" == "True" ]] \
    && pass "all entries are type=pattern" \
    || fail "type filter not applied" "$R"
}

test_search() {
  echo "POST /biblion/search"
  R=$(curl -sf -X POST "$BASE/biblion/search" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"dependency injection testing\",\"project_id\":\"$PROJECT\"}")
  COUNT=$(echo "$R" | jget "len(d)")
  [[ "$COUNT" -ge 1 ]] \
    && pass "search returned $COUNT result(s)" \
    || fail "search returned no results (score might be below threshold)" "$R"
  # Verify result shape if there are results
  if [[ "$COUNT" -ge 1 ]]; then
    echo "$R" | jget "d[0]['similarity']" > /dev/null \
      && pass "similarity field present" \
      || fail "similarity missing in result"
    echo "$R" | jget "d[0]['content']" > /dev/null \
      && pass "content field present" \
      || fail "content missing in result"
  fi
}

test_delete_entry() {
  echo "DELETE /biblion/$ENTRY_ID"
  if [[ -z "$ENTRY_ID" ]]; then
    skip "no entry_id from write test"
    return
  fi
  R=$(curl -sf -X DELETE "$BASE/biblion/$ENTRY_ID")
  jeq "$R" "d['deleted']" "True" \
    && pass "deleted=true" \
    || fail "delete failed" "$R"

  # Verify it's gone
  R2=$(curl -sf "$BASE/biblion/list?project_id=$PROJECT")
  REMAINING=$(echo "$R2" | jget "sum(1 for e in d if e['id'] and '$ENTRY_ID' in e['id'])")
  [[ "$REMAINING" == "0" ]] \
    && pass "entry no longer in list" \
    || fail "entry still present after delete"
}

test_write_second_for_clear() {
  # Write a fresh entry so clear has something to remove
  curl -sf -X POST "$BASE/biblion/write" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"config\",\"content\":\"Environment variables should be validated at startup\",\"project_id\":\"$PROJECT\"}" \
    > /dev/null
}

test_clear_project() {
  echo "DELETE /biblion/clear?project_id=$PROJECT"
  R=$(curl -sf -X DELETE "$BASE/biblion/clear?project_id=$PROJECT")
  echo "$R" | jget "d['deleted']" > /dev/null \
    && pass "deleted count returned" \
    || fail "unexpected response" "$R"

  # Confirm list is now empty for this project
  R2=$(curl -sf "$BASE/biblion/list?project_id=$PROJECT")
  COUNT=$(echo "$R2" | jget "len(d)")
  [[ "$COUNT" -eq 0 ]] \
    && pass "list empty after clear" \
    || fail "entries still present after clear ($COUNT)"
}

# ── run ───────────────────────────────────────────────────────────────────────
echo "========================================"
echo " Biblion endpoint tests"
echo "========================================"
check_prerequisites

test_health;            echo ""
test_status_ready;      echo ""
test_write;             echo ""
test_write_dedup;       echo ""
test_list;              echo ""
test_list_project_filter; echo ""
test_list_type_filter;  echo ""
test_search;            echo ""
test_delete_entry;      echo ""
test_write_second_for_clear
test_clear_project;     echo ""

echo "========================================"
echo -e " ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}"
echo "========================================"
[[ "$FAIL" -eq 0 ]]
