#!/usr/bin/env bash
# Indexer endpoint tests — runs against the live container.
# Reads local files and sends content over HTTP (no volume mounts).
# Skipped entirely if the container, Redis, or embedding server are unavailable.

set -uo pipefail

BASE="${BIBLION_URL:-http://localhost:18765}"
PROJECT="_curl_test_indexer"
SOURCE_DIR="${INDEXER_SOURCE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/indexer}"
PASS=0
FAIL=0

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; RESET='\033[0m'

pass() { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${RESET} $1"; [[ -n "${2:-}" ]] && echo "      $2"; FAIL=$((FAIL + 1)); }

jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
jeq()  { [[ "$(echo "$1" | jget "$2")" == "$3" ]]; }

# ── build ingest payload ──────────────────────────────────────────────────────
# Mirrors the logic in biblion-watch.sh:
#   - git ls-files when inside a git repo (respects .gitignore)
#   - os.walk fallback otherwise
#   - EXTENSIONS + MAX_BYTES filter
# All files are sent as "changed" (no marker — test always sends full content).
build_payload() {
  local project_id="$1" root="$2"
python3 - "$project_id" "$root" <<'PYEOF'
import json, os, subprocess, sys

project_id, root = sys.argv[1], sys.argv[2]

EXTENSIONS = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.java',
    '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.swift', '.kt',
    '.md', '.txt', '.yaml', '.yml', '.toml', '.json', '.sh',
}
SKIP_DIRS = {
    'node_modules', '__pycache__', '.venv', 'venv',
    '.mypy_cache', '.pytest_cache', 'dist', 'build', '.next', 'target',
}
MAX_BYTES = 512 * 1024

try:
    r = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=root, capture_output=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError()
    rel_paths = [p for p in r.stdout.decode(errors='replace').split('\0') if p]
except Exception:
    rel_paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fname in filenames:
            rel_paths.append(os.path.relpath(os.path.join(dirpath, fname), root))

files = []
all_paths = []

for rel in rel_paths:
    if os.path.splitext(rel)[1].lower() not in EXTENSIONS:
        continue
    fpath = os.path.join(root, rel)
    try:
        st = os.stat(fpath)
    except OSError:
        continue
    if st.st_size > MAX_BYTES:
        continue
    all_paths.append(rel)
    try:
        content = open(fpath, errors='replace').read()
    except Exception:
        continue
    files.append({'path': rel, 'content': content, 'mtime': st.st_mtime_ns / 1_000_000})

print(json.dumps({'project_id': project_id, 'files': files, 'all_paths': all_paths}))
PYEOF
}

# ── prerequisites ─────────────────────────────────────────────────────────────
check_prerequisites() {
  echo "Checking prerequisites..."

  if ! curl -sf "$BASE/health" > /dev/null 2>&1; then
    echo -e "${YELLOW}Container not reachable at $BASE — skipping all tests.${RESET}"
    exit 0
  fi

  STATUS=$(curl -sf "$BASE/indexer/status" 2>/dev/null)
  if [[ "$(echo "$STATUS" | jget "d['status']")" != "ok" ]]; then
    REASON=$(echo "$STATUS" | jget "d.get('reason','unknown')")
    echo -e "${YELLOW}Indexer not ready ($REASON) — skipping all tests.${RESET}"
    exit 0
  fi

  BIB=$(curl -sf "$BASE/biblion/status" 2>/dev/null)
  if [[ "$(echo "$BIB" | jget "d['type']")" != "ready" ]]; then
    echo -e "${YELLOW}Biblion not ready (embedding may be down) — skipping all tests.${RESET}"
    exit 0
  fi

  if [[ ! -d "$SOURCE_DIR" ]]; then
    echo -e "${YELLOW}SOURCE_DIR not found: $SOURCE_DIR — skipping all tests.${RESET}"
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
INGEST_PAYLOAD=""   # shared between tests that need it

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

test_ingest() {
  echo "POST /indexer/ingest (source: $SOURCE_DIR)"
  INGEST_PAYLOAD=$(build_payload "$PROJECT" "$SOURCE_DIR")
  FILE_COUNT=$(echo "$INGEST_PAYLOAD" | jget "len(d['files'])")
  [[ "$FILE_COUNT" -gt 0 ]] \
    && pass "built payload with $FILE_COUNT file(s)" \
    || { fail "no indexable files found in $SOURCE_DIR"; return; }

  R=$(echo "$INGEST_PAYLOAD" | curl -sf -X POST "$BASE/indexer/ingest" \
    -H "Content-Type: application/json" -d @-)
  jeq "$R" "d['project_id']" "$PROJECT" \
    && pass "project_id echoed" \
    || fail "wrong project_id" "$R"
  INDEXED=$(echo "$R" | jget "d['indexed']")
  [[ "$INDEXED" -gt 0 ]] \
    && pass "indexed $INDEXED chunk(s)" \
    || fail "nothing indexed" "$R"
  ERRORS=$(echo "$R" | jget "len(d['errors'])")
  [[ "$ERRORS" -eq 0 ]] \
    && pass "no errors" \
    || fail "$ERRORS error(s) during ingest" "$R"
}

test_status_shows_project() {
  echo "GET /indexer/status (after ingest)"
  R=$(curl -sf "$BASE/indexer/status")
  HAS=$(echo "$R" | jget "'$PROJECT' in d['projects']")
  [[ "$HAS" == "True" ]] \
    && pass "project '$PROJECT' listed" \
    || fail "project not found in status" "$R"
}

test_ingest_idempotent() {
  echo "POST /indexer/ingest (re-send same files — all skipped)"
  R=$(echo "$INGEST_PAYLOAD" | curl -sf -X POST "$BASE/indexer/ingest" \
    -H "Content-Type: application/json" -d @-)
  INDEXED=$(echo "$R" | jget "d['indexed']")
  SKIPPED=$(echo "$R" | jget "d['skipped']")
  [[ "$INDEXED" -eq 0 ]] \
    && pass "nothing re-indexed (mtime unchanged)" \
    || fail "unexpected re-indexing of $INDEXED chunks" "$R"
  [[ "$SKIPPED" -gt 0 ]] \
    && pass "$SKIPPED file(s) skipped as unchanged" \
    || fail "expected skipped > 0" "$R"
}

test_ingest_deletion_detection() {
  echo "POST /indexer/ingest (remove a file — should delete its chunks)"
  # Build a payload that omits one indexed file from all_paths.
  # Use the first file that was sent with content (guaranteed to have chunks).
  REDUCED=$(echo "$INGEST_PAYLOAD" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if not d['files']:
    print(json.dumps(d)); sys.exit()
# Pick the largest file — most likely to have produced indexed chunks
target = max(d['files'], key=lambda f: len(f['content']))
removed = target['path']
d['all_paths'] = [p for p in d['all_paths'] if p != removed]
d['files'] = []   # no content to re-index, just signal the deletion
print(json.dumps(d))
")
  R=$(echo "$REDUCED" | curl -sf -X POST "$BASE/indexer/ingest" \
    -H "Content-Type: application/json" -d @-)
  DELETED=$(echo "$R" | jget "d['deleted']")
  [[ "$DELETED" -gt 0 ]] \
    && pass "deleted $DELETED chunk(s) for removed file" \
    || fail "no chunks deleted" "$R"
}

test_search() {
  echo "POST /indexer/search"
  # Re-ingest to restore the file removed in the deletion test
  echo "$INGEST_PAYLOAD" | curl -sf -X POST "$BASE/indexer/ingest" \
    -H "Content-Type: application/json" -d @- > /dev/null

  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"redis storage index\",\"project_id\":\"$PROJECT\"}")
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -ge 1 ]] \
    && pass "search returned $COUNT result(s)" \
    || fail "no results (score may be below threshold)" "$R"
  if [[ "$COUNT" -ge 1 ]]; then
    echo "$R" | jget "d['results'][0]['file_path']" > /dev/null && pass "file_path present" || fail "file_path missing"
    echo "$R" | jget "d['results'][0]['score']"     > /dev/null && pass "score present"     || fail "score missing"
    echo "$R" | jget "d['results'][0]['start_line']" > /dev/null && pass "start_line present" || fail "start_line missing"
    echo "$R" | jget "d['results'][0]['text']"      > /dev/null && pass "text present"       || fail "text missing"
  fi
}

test_search_top_k() {
  echo "POST /indexer/search (top_k=1)"
  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"redis\",\"project_id\":\"$PROJECT\",\"top_k\":1}")
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -le 1 ]] \
    && pass "top_k=1 respected (got $COUNT)" \
    || fail "too many results ($COUNT) for top_k=1"
}

test_search_unknown_project() {
  echo "POST /indexer/search (unknown project)"
  R=$(curl -sf -X POST "$BASE/indexer/search" \
    -H "Content-Type: application/json" \
    -d '{"query":"anything","project_id":"_no_such_project_"}')
  COUNT=$(echo "$R" | jget "len(d['results'])")
  [[ "$COUNT" -eq 0 ]] \
    && pass "empty results for unknown project" \
    || fail "unexpected results ($COUNT)"
}

test_clear() {
  echo "DELETE /indexer/clear"
  R=$(curl -sf -X DELETE "$BASE/indexer/clear" \
    -H "Content-Type: application/json" \
    -d "{\"project_id\":\"$PROJECT\"}")
  jeq "$R" "d['project_id']" "$PROJECT" \
    && pass "project_id echoed" \
    || fail "wrong project_id" "$R"
  DELETED=$(echo "$R" | jget "d['deleted']")
  [[ "$DELETED" -gt 0 ]] \
    && pass "deleted $DELETED key(s)" \
    || fail "nothing deleted" "$R"

  R2=$(curl -sf "$BASE/indexer/status")
  STILL=$(echo "$R2" | jget "'$PROJECT' in d['projects']")
  [[ "$STILL" == "False" ]] \
    && pass "project removed from status" \
    || fail "project still listed after clear"
}

# ── run ───────────────────────────────────────────────────────────────────────
echo "========================================"
echo " Indexer endpoint tests"
echo "========================================"
check_prerequisites

test_status_ok;               echo ""
test_ingest;                  echo ""
test_status_shows_project;    echo ""
test_ingest_idempotent;       echo ""
test_ingest_deletion_detection; echo ""
test_search;                  echo ""
test_search_top_k;            echo ""
test_search_unknown_project;  echo ""
test_clear;                   echo ""

echo "========================================"
echo -e " ${GREEN}${PASS} passed${RESET}  ${RED}${FAIL} failed${RESET}"
echo "========================================"
[[ "$FAIL" -eq 0 ]]
