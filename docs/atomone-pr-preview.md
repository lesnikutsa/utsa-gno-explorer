# Isolated AtomOne pull request preview

This procedure does not modify the production checkout, web root, services, database, Nginx, or firewall. It deliberately refuses to reuse `/opt/utsa-gno-explorer-review-atomone`. The Gno endpoints require an existing PostgreSQL database; provide a dedicated, explicitly read-only connection string without printing it.

## Prepare a separate checkout and build

Replace `<PR-REF>` with the review branch or pull request ref and provide `REVIEW_DATABASE_URL` through a protected shell environment.

```bash
bash -euo pipefail <<'PREPARE'
review=/opt/utsa-gno-explorer-review-atomone-unified
test ! -e "$review" || { echo "Refusing to overwrite $review" >&2; exit 1; }
git clone --no-local /path/to/utsa-gno-explorer "$review"
cd "$review"
git fetch origin '<PR-REF>'
git checkout --detach FETCH_HEAD
python3.10 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm --prefix frontend ci
VITE_API_PROXY_TARGET=http://127.0.0.1:18181 npm --prefix frontend run build
PREPARE
```

## Start the review API and frontend

The checks stop setup on conflicts but do not terminate the interactive parent shell. Vite is given an explicit review proxy, so `/api` cannot silently fall back to production port 18180.

```bash
bash -euo pipefail <<'START'
review=/opt/utsa-gno-explorer-review-atomone-unified
session=utsa-atomone-unified-review
: "${REVIEW_DATABASE_URL:?Set a dedicated read-only PostgreSQL URL}"
command -v tmux >/dev/null
! tmux has-session -t "$session" 2>/dev/null || { echo "tmux session already exists" >&2; exit 1; }
for port in 18181 4174; do
  ! ss -H -ltn "sport = :$port" | grep -q . || { echo "Port $port is already occupied" >&2; exit 1; }
done
cd "$review"
tmux new-session -d -s "$session" -n api \
  "DATABASE_URL=\"$REVIEW_DATABASE_URL\" .venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 18181; status=\$?; echo API exited with \$status; exec bash"
tmux new-window -t "$session" -n frontend \
  "VITE_API_PROXY_TARGET=http://127.0.0.1:18181 npm --prefix frontend run preview -- --host 127.0.0.1 --port 4174 --strictPort; status=\$?; echo Frontend exited with \$status; exec bash"
tmux attach -t "$session"
START
```
