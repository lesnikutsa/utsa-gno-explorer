# AtomOne frontend review preview

This preview is isolated from the production API, web root, database, indexer, and
background services. It requires the backend from PR #182 and binds that review API
only to `127.0.0.1:18181`. The frontend proxy target is explicitly overridden so it
cannot fall back to the production port `18180`.

Run the following in a dedicated review checkout. The commands create two tmux
windows and leave the session open if either process exits with an error:

```bash
cd /path/to/review-checkout
python -m venv .venv-review
.venv-review/bin/pip install -r requirements.txt -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
tmux new-session -d -s atomone-review -n api \
  "cd '$PWD'; .venv-review/bin/uvicorn api.main:app --host 127.0.0.1 --port 18181; status=\$?; echo \"review API exited (\$status)\"; exec bash"
tmux new-window -t atomone-review -n frontend \
  "cd '$PWD/frontend'; VITE_REVIEW_API_TARGET=http://127.0.0.1:18181 npm run preview -- --host 127.0.0.1 --port 4174 --strictPort; status=\$?; echo \"review frontend exited (\$status)\"; exec bash"
tmux attach -t atomone-review
```

Open `http://127.0.0.1:4174`. Stop only these preview processes with:

```bash
tmux kill-session -t atomone-review
```
