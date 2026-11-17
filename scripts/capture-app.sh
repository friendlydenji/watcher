#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"

if (( $# < 1 )); then
    printf 'Usage: %s <built-program> [program arguments...]\n' "$0" >&2
    exit 2
fi
program=$1
shift
if [[ ! -x "$program" ]]; then
    printf 'Program is not executable: %s\n' "$program" >&2
    exit 1
fi
if ! command -v trace-cmd >/dev/null 2>&1; then
    printf 'trace-cmd is missing; install it with: sudo apt install trace-cmd\n' >&2
    exit 1
fi

comm=$(basename -- "$program")
comm=${comm:0:15}
mkdir -p traces
stamp=$(date +%Y%m%d-%H%M%S)
trace_file="traces/capture-${comm}-${stamp}-$$.dat"
event_file="${trace_file%.dat}.events.log"
event_path="$project_root/$event_file"

trace_command=(trace-cmd)
user_option=()
if (( EUID != 0 )); then
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'sudo is required for kernel tracing\n' >&2
        exit 1
    fi
    trace_command=(sudo trace-cmd)
    user_option=(--user "$(id -un)")
fi

"${trace_command[@]}" record -C mono "${user_option[@]}" -o "$trace_file" \
    -e sched:sched_switch \
    -e sched:sched_wakeup \
    -e sched:sched_waking \
    -e sched:sched_wakeup_new \
    -e sched:sched_process_fork \
    -e sched:sched_process_exit \
    -- env "LTI_EVENT_FILE=$event_path" "$program" "$@"

if (( EUID != 0 )); then
    sudo chown "$(id -u):$(id -g)" "$trace_file"
fi

python3 scripts/analyze_sched.py "$trace_file" --events "$event_path"
if ! python3 scripts/analyze_flow.py "$trace_file"; then
    printf 'Flow CSV unavailable; check SDK event capture.\n' >&2
fi
if ! python3 scripts/analyze_sync.py "$trace_file"; then
    printf 'Sync CSV unavailable; check SDK event capture.\n' >&2
fi
if [[ -f "${trace_file%.dat}.flow.csv" && -f "${trace_file%.dat}.sync.csv" ]]; then
    python3 scripts/correlate.py "$trace_file"
fi
printf '\nTrace: %s\n' "$trace_file"
printf 'Open it with: kernelshark %s\n' "$trace_file"
