#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"
if (( $# < 2 )); then
    printf 'Usage: %s <capture_seconds> <built-program> [program arguments...]\n' "$0" >&2
    exit 2
fi
duration=$1
shift
if [[ ! "$duration" =~ ^[1-9][0-9]*$ ]] || (( duration > 120 )); then
    printf 'capture_seconds must be 1..120\n' >&2
    exit 2
fi
program=$1
shift
if [[ ! -x "$program" ]]; then
    printf 'Program is not executable: %s\n' "$program" >&2
    exit 1
fi
if ! command -v trace-cmd >/dev/null 2>&1; then
    printf 'trace-cmd is missing\n' >&2
    exit 1
fi

comm=$(basename -- "$program")
mkdir -p traces
stamp=$(date +%Y%m%d-%H%M%S)
report_file="traces/live-${comm}-${stamp}-$$.txt"
prefix=${report_file%.txt}
event_path="$project_root/${prefix}.events.log"
session_path="$project_root/${prefix}.session.json"

trace_command=(trace-cmd)
reader_command=(python3)
privileged=()
if (( EUID != 0 )); then
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'sudo is required for kernel tracing\n' >&2
        exit 1
    fi
    privileged=(sudo)
    trace_command=(sudo trace-cmd)
    reader_command=(sudo python3)
fi

printf 'Live scheduler report: %s\n' "$report_file"
tracefs=/sys/kernel/tracing
if ! "${privileged[@]}" test -d "$tracefs/instances"; then
    tracefs=/sys/kernel/debug/tracing
fi
if ! "${privileged[@]}" test -d "$tracefs/instances"; then
    printf 'Private tracefs instances are required; refusing to modify global tracing.\n' >&2
    exit 1
fi
instance="watcher-${UID}-$$-${stamp}"
if "${privileged[@]}" test -e "$tracefs/instances/$instance"; then
    printf 'Trace instance already exists: %s\n' "$instance" >&2
    exit 1
fi
reader_pid=
app_pid=
instance_started=0
finished=0
gate_dir=$(mktemp -d)
mkfifo "$gate_dir/start"
cleanup() {
    if [[ -n "$reader_pid" ]] && kill -0 "$reader_pid" 2>/dev/null; then
        kill -TERM "$reader_pid" 2>/dev/null || true
        wait "$reader_pid" 2>/dev/null || true
    fi
    if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
        kill -TERM "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if (( ! finished )); then
        python3 scripts/live_session.py "$session_path" failed "${app_pid:-0}" || true
    fi
    rm -f -- "$gate_dir/start"
    rmdir -- "$gate_dir" 2>/dev/null || true
    if (( instance_started )); then
        "${trace_command[@]}" stop -B "$instance" >/dev/null 2>&1 || true
        "${trace_command[@]}" reset -B "$instance" -d >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# The gate preserves this PID across exec and prevents untraced startup.
env "LTI_EVENT_FILE=$event_path" python3 scripts/run_gated.py \
    "$gate_dir/start" "$program" "$@" &
app_pid=$!
python3 scripts/live_session.py "$session_path" starting "$app_pid"

# Filter the private buffer to this PID and inherit tracing in new threads.
# Never fall back to recording the entire system if this is unsupported.
instance_started=1
"${trace_command[@]}" start -B "$instance" -C mono -P "$app_pid" -c \
    -e sched:sched_switch \
    -e sched:sched_wakeup \
    -e sched:sched_waking \
    -e sched:sched_wakeup_new

stream_duration=$(( duration + 2 ))
"${reader_command[@]}" scripts/read_trace.py \
    "$tracefs/instances/$instance/trace_pipe" "$stream_duration" > "$report_file" &
reader_pid=$!

# The private buffer is recording; let the pipe reader open.
sleep 0.2
if ! kill -0 "$reader_pid" 2>/dev/null; then
    printf 'scheduler stream reader exited early\n' >&2
    exit 1
fi
python3 scripts/live_session.py "$session_path" recording "$app_pid"
printf '1' > "$gate_dir/start"
app_status=0
wait "$app_pid" || app_status=$?
python3 scripts/live_session.py "$session_path" draining "$app_pid"
app_pid=
reader_status=0
wait "$reader_pid" || reader_status=$?
reader_pid=
if (( reader_status != 0 && reader_status != 124 )); then
    printf 'trace_pipe reader failed with status %d\n' "$reader_status" >&2
    exit "$reader_status"
fi
finished=1
cleanup
trap - EXIT INT TERM

python3 scripts/analyze_sched.py "$report_file" --events "$event_path"
python3 scripts/analyze_flow.py "$report_file"
python3 scripts/analyze_sync.py "$report_file"
python3 scripts/correlate.py "$prefix"
python3 scripts/live_session.py "$session_path" complete 0
printf 'Live run complete: %s\n' "$prefix"

exit "$app_status"
