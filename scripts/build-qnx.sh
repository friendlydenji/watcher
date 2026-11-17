#!/usr/bin/env bash
set -euo pipefail
if (( $# != 3 )); then
    printf 'Usage: %s <SDP directory> <qcc variant> <new output directory>\n' "$0" >&2
    exit 2
fi
sdp=$1
variant=$2
output=$3
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ! -f "$sdp/qnxsdp-env.sh" ]]; then printf 'Missing SDP environment\n' >&2; exit 1; fi
# Compiler environment scripts may reference unset variables.
set +u
source "$sdp/qnxsdp-env.sh" >/dev/null
set -u
mkdir -p "$output"
output=$(cd "$output" && pwd)
case "$variant" in
    gcc_ntoaarch64le*) archiver="$QNX_HOST/usr/bin/ntoaarch64-ar" ;;
    gcc_ntox86_64*) archiver="$QNX_HOST/usr/bin/ntox86_64-ar" ;;
    gcc_ntoarmv7le*) archiver="$QNX_HOST/usr/bin/ntoarmv7-ar" ;;
    *) printf 'Specify an available qcc variant; see qcc -V\n' >&2;exit 2 ;;
esac
cd "$project_root"
flags=(-V"$variant" -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror -Isdk/include)
qcc "${flags[@]}" -c sdk/src/lti.c -o "$output/lti.o"
"$archiver" rcs "$output/liblti.a" "$output/lti.o"
qcc "${flags[@]}" examples/c_demo/main.c "$output/liblti.a" -o "$output/c_pingpong"
qcc "${flags[@]}" examples/job_only/main.c "$output/liblti.a" -o "$output/job_only"
qcc "${flags[@]}" tests/benchmark_events.c "$output/liblti.a" -o "$output/benchmark_events"
qcc "${flags[@]}" tests/test_portable.c "$output/liblti.a" -o "$output/test_portable"
qcc "${flags[@]}" tools/qnx_capture.c -o "$output/watcher-qnx-capture"
qcc "${flags[@]}" -c demo/worker.c -o "$output/worker.o"
q++ -V"$variant" -O2 -std=c++17 -Wall -Wextra -Wpedantic -Werror -Isdk/include demo/main.cpp "$output/worker.o" "$output/liblti.a" -o "$output/mixed_demo"
printf 'Built QNX artifacts in %s\n' "$output"
