#!/usr/bin/env bash
# ponytail: assumes single Ubuntu/Debian host with systemd; upgrade: Ansible/SSH runner if multi-host
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

echo "==> [1/5] Pulling latest changes from git..."
git pull --ff-only

echo "==> [2/5] Updating Python package in virtualenv..."
"${REPO_DIR}/.venv/bin/pip" install -e .

echo "==> [3/5] Stopping services for safe schema migration..."
# ponytail: stops services so SQLite DDL migration gets exclusive lock; upgrade: blue-green if zero-downtime required
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl stop dividend-web dividend-worker 2>/dev/null || true
fi

echo "==> [4/5] Running database migrations..."
"${REPO_DIR}/.venv/bin/alembic" upgrade head

echo "==> [5/5] Restarting services..."
if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl start dividend-worker dividend-web
    echo "==> Deployment successful!"
    sudo systemctl status dividend-web dividend-worker --no-pager -n 0 || true
else
    echo "==> [INFO] systemctl not available; migrations applied successfully."
fi
