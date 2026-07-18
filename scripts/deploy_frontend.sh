#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${REPO_ROOT}/frontend/dist"
PUBLIC_DIR="/var/www/utsa-gno-explorer"

if [ "${EUID}" -ne 0 ]; then
  echo "deploy_frontend.sh must be run as root on exp2." >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required for frontend deployment; install rsync and retry." >&2
  exit 1
fi

if [ ! -f "${DIST_DIR}/index.html" ]; then
  echo "Missing ${DIST_DIR}/index.html. Run npm run build in frontend before deploying." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "${PUBLIC_DIR}"
rsync -a --delete --chown=root:root "${DIST_DIR}/" "${PUBLIC_DIR}/"
find "${PUBLIC_DIR}" -type d -exec chmod 0755 {} +
find "${PUBLIC_DIR}" -type f -exec chmod 0644 {} +

nginx -t
systemctl reload nginx
