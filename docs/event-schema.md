# LTI event schema v1

Applications call the SDK; they do not format event strings themselves. The
same phase names and identifiers are used by both backends.

With `LTI_EVENT_FILE` set, each event is appended to that file:

```text
LTI_EVENT mono_ns=<CLOCK_MONOTONIC nanoseconds> tid=<Linux TID> pid=<PID> job=<uint64> phase=<name> v=1 resource=<uint64>
```

Without `LTI_EVENT_FILE`, the SDK tries Linux `trace_marker`:

```text
LTI job=<uint64> phase=<name> v=1 pid=<PID> resource=<uint64>
```

For the second format, `trace-cmd report` supplies the timestamp and TID.
Capture scripts select the `mono` trace clock so scheduler and file events
can be compared. `(PID, job ID)` identifies a flow across threads in one
process. `job=0` means no job is known. Resource IDs are application assigned
and unique within a process; `resource=0` means no associated resource.

| Phase | Meaning |
| --- | --- |
| `send`, `receive`, `done` | Queue entry, consumer pickup, completion |
| `compute_begin`, `compute_end` | Application-defined compute window |
| `sleep_begin`, `sleep_end` | Application-defined sleep window |
| `lock_wait`, `lock_acquired`, `lock_release` | Mutex operation boundaries |
| `cond_wait_begin`, `cond_wait_end` | Condition wait call boundaries |

`compute_wall_ms` is elapsed time and can include preemption. The job
breakdown separately reports scheduler `running`, `runnable`, `sleeping`,
`other`, and `unknown` time within receive→done. Synchronization intervals
can overlap these states. `cond_wait` includes wakeup and mutex reacquisition.
Incomplete flows are excluded from latency and breakdown results. Event loss,
capture start delay, and PID reuse in long captures are not resolved in v1.
Cross-process flows also require an explicit shared identifier and are not
supported by this schema.

The file backend lets the application run without tracefs privileges. The
collector still needs privileged access to Linux scheduler tracing. When no
backend can be opened, event recording is a no-op and the pthread wrappers
continue to perform the requested synchronization.

## Release boundary and SDK overhead

`lock_release` is recorded immediately **before** `pthread_mutex_unlock`,
while the calling thread still owns the mutex. This prevents a succeeding
holder from recording `lock_acquired` before the previous release marker.
The boundary is an attempted release: if pthread rejects the unlock, the
marker alone does not prove success. Valid mutex ownership and checking
pthread return codes remain the application's responsibility. Condition-wait
release markers likewise precede the call that releases the mutex internally.

The file backend caches Linux TID in C11 thread-local storage, resetting it in
the child of an ordinary `fork()` with a pthread atfork handler. Raw fork/clone
syscalls bypass that handler and are outside this cache contract. Events still
format and write synchronously, so instrumentation has a measurable cost.
SDK event writes preserve the calling thread's `errno`.

## Saved dashboard data (additive schema v1 fields)

`jobs.json` includes `timeline`, `sync`, `events`, and `scheduler`. The first
two contain the analyzed CSV rows; the latter two preserve normalized SDK and
scheduler observations for replay and export. `events[].time_s` and scheduler
timestamps use the same monotonic clock as timeline intervals. Legacy JSON
without these additive fields remains usable for job and state timelines;
wakeup arrows/raw events are unavailable if the observations were not saved.
The dashboard does not infer closed scheduler states beyond the last
observed transition of a replay. Uncovered intervals remain unknown.


## QNX 7.1 / 8.0 transport and clock

On Linux, `mono_ns` is CLOCK_MONOTONIC nanoseconds. On QNX, `mono_ns` is
monotonic nanoseconds derived from `ClockCycles()` and the system-page
`cycles_per_sec`, using the cycle-counter epoch. It is NOT assumed to have
the same epoch as QNX CLOCK_MONOTONIC. This avoids tick-quantized timestamps
observed on the tested QNX 7.1 system. Do not compare absolute timestamps
between hosts or OSes without an additional synchronization scheme.

The QNX file backend writes `<event-file>.clock.json`. The native backend
inserts `LTI_CLOCK { ... }` using user event `LTI_QNX_EVENT_ID - 1` and the
ordinary event strings using `LTI_QNX_EVENT_ID` (default 1019 and 1020).
Reserve both IDs in the application. The SDK only inserts native events;
it never configures, resets, starts or stops the global QNX tracer.

QNX thread IDs are scoped to PID. QNX scheduler rows include `pid`; correlation
uses `(PID,TID)`. Dashboard `track_id` is an internal dense drawing key; native
`tid` and `pid` stay unchanged and are shown to the user.

A missing synchronization annotation now produces JSON `null`, not zero,
for `mutex_wait_observed_ms` / `cond_wait_observed_ms`. An empty or absent
sync CSV does not prevent job correlation. A measured zero is represented
only when an associated interval exists but its overlap with the job is zero.

The QNX file backend serializes complete records to avoid measured same-FD
contention. It is synchronous and can block. The native TraceEvent backend
bypasses this file mutex. Fork handlers reset the cached native identity and
reinitialize the child's private file mutex; this was tested on QNX 7.1.
`lti_write_errors()` reports failed/short writes and failed insertion/clock
operations; it cannot prove that an external collector retained every event.
