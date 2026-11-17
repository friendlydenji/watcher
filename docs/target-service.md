# Target service: protocol and verification

The supported user workflow is in [README section 5](../README.md#5-mở-trình-duyệt-xem-live-trực-tiếp-từ-qnx).

## Architecture

`watcher-service` is a C11/POSIX HTTP process. It launches the local capture
helper with an explicit CLI application argv and serves a fixed allowlist
of UI assets plus read-only live data. No HTTP endpoint accepts a command,
filesystem path, PID to control, or shell script. `--wait-client` starts the
CLI-configured capture on the first live request.

The helper owns its child application and tracelogger, checks for another
collector and uses the existing capture lock. Native SDK user events and
Thread-class kernel events share the QNX cycle clock. The service uses the
capture header's cycle frequency and the parser's full 64-bit timestamp.
Only the launched application PID is retained during live collection.

The statically linked `libtraceparser` is called once per capture. A
thread-local `fread` adapter waits at temporary EOF until the file grows or
the collector has finished; all other threads retain ordinary stdio
behavior. This preserves the parser's clock/combine/reordering state and
avoids reparsing historical data. The callback API closes state intervals
only when another transition was observed. The browser correlates jobs
using integer nanoseconds and preserves uint64 job/resource IDs as strings.

## API and retention

- `GET /`: dashboard assets are loaded from `--ui`.
- `GET /api/traces`: empty list for this single-session service.
- `GET /api/live`: bounded SDK events, native transitions, identities,
  CPUs, state/error/retention metadata. This is a snapshot API, not a delta
  transport. Browser polling is 500 ms; bandwidth grows with retained data.
- Export is generated in the browser from the currently retained snapshot.
- Other paths return 404; methods other than GET return 405.

RAM retention is 20,000 SDK events, 20,000 transitions and 1,024 identities;
old records are evicted and `history_limited` is exposed. It is not a
full-session archive after eviction. Raw `.kev` remains on target and grows
for the duration of collection. The service does not implement disk
rotation, TLS, authentication, cross-process jobs or attach-by-PID.

Worker stack sizes are explicitly 512 KiB. Actual resident memory depends
on how much stack/data is touched and the current HTTP snapshot; the stack
reservation is not a measured resident-memory value. SDK hot-path code is
unchanged; collection and network work are outside the application process.
No zero-overhead, bounded-latency or WCET guarantee is made.

## Verification, 2026-11-17

- QNX 7.1 AArch64, R-Car V4H, live browser connecting directly to target:
  80 submitted/completed jobs, all 80 correlated with complete scheduler;
  1,366 SDK markers, 961 native transitions, exactly 2 app threads, CPUs
  0/1/2/3. CPU and jobs were observed on 9 browser samples during execution.
  Collector diagnostics were empty; no JavaScript errors.
- Existing QNX native capture: 60 SDK markers / 20 jobs, all complete,
  decoded by the target service without Python or traceprinter.
- SIGTERM during collection: the owned app/logger exited and capture lock
  was removed. The completed service on another port remained running.
- Build: QNX 7.1 AArch64, x86_64, ARMv7; QNX 8.0 AArch64 and x86_64.
  No runtime verification on QNX 8.0 is claimed.
- Existing C/Python/JS checks and browser regression passed. Additional
  service tests exercise incremental reads, live correlation, large IDs,
  missing scheduler/loss, optional synchronization, export and HTTP guards.

## Reference

- [QNX 7.1 traceparser](https://www.qnx.com/developers/docs/7.1/com.qnx.doc.neutrino.lib_ref/topic/t/traceparser.html)
- [QNX 8.0 traceparser](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/traceparser.html)
