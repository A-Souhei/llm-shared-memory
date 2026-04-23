#!/usr/bin/env bash
# biblion-watch.sh — drop in your project root and run it.
#
# Watches for file changes and keeps the biblion indexer up to date.
# Communicates with the biblion container over HTTP — no volume mounts needed.
# Respects .gitignore when inside a git repository.
#
# Config (env vars):
#   BIBLION_URL      server base URL        (default: http://localhost:18765)
#   BIBLION_PROJECT  project identifier     (default: git repo name or directory name)
#   BIBLION_INTERVAL seconds between scans  (default: 30)

set -uo pipefail

BIBLION_URL="${BIBLION_URL:-http://localhost:18765}"
BIBLION_INTERVAL="${BIBLION_INTERVAL:-30}"
ROOT="$(cd "${1:-.}" && pwd)"

# Derive project id from git remote or directory name
if [[ -z "${BIBLION_PROJECT:-}" ]]; then
  BIBLION_PROJECT=$(git remote get-url origin 2>/dev/null \
    | sed 's|.*/||; s|\.git$||') || true
  [[ -z "${BIBLION_PROJECT:-}" ]] && BIBLION_PROJECT="$(basename "$ROOT")"
fi

MARKER="/tmp/.biblion_${BIBLION_PROJECT//[^a-zA-Z0-9_-]/_}.marker"

# ── helpers ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
log()  { echo -e "[$(date '+%H:%M:%S')] $*"; }
info() { log "${GREEN}$*${RESET}"; }
warn() { log "${YELLOW}$*${RESET}"; }
err()  { log "${RED}$*${RESET}"; }

check_server() {
  curl -sf "$BIBLION_URL/indexer/status" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d['status']=='ok' else 1)" \
    2>/dev/null
}

# ── build payload ─────────────────────────────────────────────────────────────
# Collects files from $ROOT:
#   - Uses `git ls-files` when inside a git repo (respects .gitignore)
#   - Falls back to os.walk + SKIP_DIRS otherwise
#   - Always filters by EXTENSIONS and MAX_BYTES
#   - Only includes files modified after $MARKER (all files on first run)
#   - Always includes all_paths (for server-side deletion detection)
build_payload() {
python3 - "$BIBLION_PROJECT" "$ROOT" "$MARKER" <<'PYEOF'
import json, os, subprocess, sys

project_id, root, marker = sys.argv[1], sys.argv[2], sys.argv[3]

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

marker_mtime = os.stat(marker).st_mtime if os.path.exists(marker) else 0

# File discovery: git ls-files (respects .gitignore) or os.walk fallback
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
    if st.st_mtime > marker_mtime:
        try:
            content = open(fpath, errors='replace').read()
        except Exception:
            continue
        files.append({
            'path': rel,
            'content': content,
            'mtime': st.st_mtime_ns / 1_000_000,
        })

print(json.dumps({'project_id': project_id, 'files': files, 'all_paths': all_paths}))
PYEOF
}

# ── one scan cycle ────────────────────────────────────────────────────────────
scan() {
  local payload n_files n_paths result
  payload=$(build_payload) || { err "Failed to scan files"; return 1; }

  n_files=$(echo "$payload" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['files']))")
  n_paths=$(echo "$payload" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['all_paths']))")

  if [[ "$n_paths" -eq 0 ]]; then
    log "No indexable files found"
    return 0
  fi

  if [[ "$n_files" -eq 0 ]]; then
    log "No changes — sending all_paths for deletion check"
  else
    log "Sending $n_files changed file(s)..."
  fi

  result=$(echo "$payload" | curl -sf -X POST "$BIBLION_URL/indexer/ingest" \
    -H "Content-Type: application/json" -d @-) || { err "Ingest request failed — will retry"; return 1; }

  python3 - "$result" <<'PYEOF'
import json, sys
d = json.loads(sys.argv[1])
parts = [f"indexed={d['indexed']}", f"skipped={d['skipped']}", f"deleted={d['deleted']}"]
if d['errors']:
    parts.append(f"errors={len(d['errors'])}")
    for e in d['errors'][:3]:
        print(f"  ! {e}", file=sys.stderr)
print("  " + "  ".join(parts))
PYEOF

  touch "$MARKER"
}

# ── main ──────────────────────────────────────────────────────────────────────
info "biblion watcher"
info "  project  : $BIBLION_PROJECT"
info "  server   : $BIBLION_URL"
info "  interval : ${BIBLION_INTERVAL}s"
info "  root     : $ROOT"
echo ""

trap 'echo ""; warn "Stopped."; exit 0' INT TERM

while true; do
  if ! check_server; then
    warn "Indexer not ready at $BIBLION_URL — retrying in ${BIBLION_INTERVAL}s"
  else
    scan
  fi
  sleep "$BIBLION_INTERVAL"
done
