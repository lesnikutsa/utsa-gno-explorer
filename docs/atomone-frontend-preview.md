# AtomOne frontend review preview

This preview uses a separate checkout, processes, build output, and ports. It requires
the backend from PR #182. It does not start an indexer or modify a web root. The API
still requires a PostgreSQL connection: create a protected `review-api.env` outside
the repository with `DATABASE_URL` for an explicitly selected **read-only review
database user**, plus the Cosmos upstream configuration required by the backend
branch. Never point this file at a production write-capable account. The commands
below load the file without printing it; they do not claim the database itself is
isolated.

Run this from a dedicated review checkout after setting `REVIEW_CHECKOUT` and
`REVIEW_ENV`. It refuses a wrong directory, occupied port, missing environment, or
existing tmux session. A failed process leaves its tmux window open for inspection.

```bash
(
  set -eu
  : "${REVIEW_CHECKOUT:?set REVIEW_CHECKOUT to the dedicated review checkout}"
  : "${REVIEW_ENV:?set REVIEW_ENV to the protected review-api.env path}"
  cd "$REVIEW_CHECKOUT"
  test -f frontend/package.json -a -f api/app.py -a -e .git
  test -r "$REVIEW_ENV"
  test "$(stat -c '%a' "$REVIEW_ENV")" = 600
  git merge-base --is-ancestor c7e61b50db23e4843c7f0a4c843cfcd5489cde53 HEAD
  ! ss -H -ltn '( sport = :18181 or sport = :4174 )' | grep -q .
  ! tmux has-session -t atomone-review 2>/dev/null
  python -m venv .venv-review
  .venv-review/bin/pip install -r requirements.txt -r requirements-dev.txt
  npm --prefix frontend ci
  npm --prefix frontend run build
  tmux new-session -d -s atomone-review -n api \
    "cd '$PWD' && set -a && source '$REVIEW_ENV' && set +a && .venv-review/bin/uvicorn api.app:app --host 127.0.0.1 --port 18181; status=\$?; echo \"review API exited (\$status)\"; exec bash"
  tmux new-window -t atomone-review -n frontend \
    "cd '$PWD/frontend' && VITE_REVIEW_API_TARGET=http://127.0.0.1:18181 npm run preview -- --host 127.0.0.1 --port 4174 --strictPort; status=\$?; echo \"review frontend exited (\$status)\"; exec bash"
  tmux attach -t atomone-review
) || printf '%s\n' 'AtomOne review setup stopped; this shell remains open.' >&2
```

Open `http://127.0.0.1:4174`. Stop only these preview processes with:

```bash
tmux kill-session -t atomone-review
```
