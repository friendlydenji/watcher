#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
duration=${1:-5}
if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 60 )); then
    printf 'Usage: %s [duration_seconds: 1..60]\n' "$0" >&2
    exit 2
fi
exec "$project_root/scripts/capture-app.sh" ./demo/mixed_demo "$duration"
