#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT/adaptive-network-analyzer"

echo "[setup] Checking dependencies..."
for cmd in docker python3; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: '$cmd' not found."; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' plugin not found."; exit 1; }

echo "[setup] Creating runtime directories..."
mkdir -p "$COMPOSE_DIR/shared_config"
mkdir -p "$COMPOSE_DIR/grafana/dashboards"

echo "[setup] Configuring environment..."
if [[ ! -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "[setup] .env created -- edit it before starting the stack."
else
    echo "[setup] .env already exists, skipping."
fi

chmod 600 "$ROOT/.env"
chmod 700 "$ROOT/scripts/setup.sh"

echo "[setup] Generating Grafana dashboard JSON..."
python3 "$COMPOSE_DIR/grafana/create_dashboard.py"

echo "[setup] Done. Run 'make build' then 'make up'."
