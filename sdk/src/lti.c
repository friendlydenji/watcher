#if defined(__linux__)
#define _GNU_SOURCE
#elif defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#error "Watcher SDK supports Linux and QNX Neutrino"
#endif
#include "lti/lti.h"
#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#if defined(__QNXNTO__)
#include <sys/neutrino.h>
#include <sys/syspage.h>
#include <sys/trace.h>
#else
#include <sys/syscall.h>
#endif

enum backend { DISABLED, EVENT_FILE, KERNEL_MARKER, QNX_TRACE };
static enum backend backend;
static int event_fd = -1;
static int identity_cache_enabled;
static pthread_once_t fork_hook = PTHREAD_ONCE_INIT;
static atomic_uint write_errors;
#if defined(__QNXNTO__)
static uint64_t cycle_frequency;
static pthread_mutex_t output_mutex=PTHREAD_MUTEX_INITIALIZER;
static uint64_t cycle_ns(uint64_t cycles)
{
    uint64_t whole=cycles/cycle_frequency, remainder=cycles%cycle_frequency;
    uint64_t fraction=cycle_frequency<=UINT64_MAX/UINT64_C(1000000000)
        ? remainder*UINT64_C(1000000000)/cycle_frequency
        : (uint64_t)((long double)remainder*1000000000.0L/cycle_frequency);
    return whole*UINT64_C(1000000000)+fraction;
}
#endif
struct identity { char text[64]; unsigned length; };
static _Thread_local struct identity identity;

static const struct phase_name { const char *text; unsigned length; } phases[] = {
#define PHASE(s) {s, sizeof(s)-1}
    PHASE("send"), PHASE("receive"), PHASE("done"), PHASE("compute_begin"),
    PHASE("compute_end"), PHASE("sleep_begin"), PHASE("sleep_end"),
    PHASE("lock_wait"), PHASE("lock_acquired"), PHASE("lock_release"),
    PHASE("cond_wait_begin"), PHASE("cond_wait_end")
#undef PHASE
};

uint64_t lti_thread_id(void)
{
#if defined(__QNXNTO__)
    /* QNX pthread_self() is the native per-process thread ID, available in
     * 7.1 and 8.0. Linux pthread_t is not the kernel TID. */
    return (uint64_t)pthread_self();
#else
    return (uint64_t)syscall(SYS_gettid);
#endif
}

/* Bounded decimal conversion: at most 20 digits for a uint64_t. */
static char *decimal(char *out, uint64_t value)
{
    char digits[20];
    unsigned count = 0;
    do { digits[count++] = (char)('0' + value % 10); value /= 10; } while (value);
    while (count) *out++ = digits[--count];
    return out;
}
#define APPEND(out, literal) do { \
    memcpy(out, literal, sizeof(literal)-1); (out) += sizeof(literal)-1; \
} while (0)

#if defined(__QNXNTO__)
static void before_fork(void) { (void)pthread_mutex_lock(&output_mutex); }
static void after_fork(void) { (void)pthread_mutex_unlock(&output_mutex); }
#endif
static void reset_child_identity(void)
{
    identity.length = 0;
#if defined(__QNXNTO__)
    /* QNX copied mutex ownership belongs to the parent PID. The child is
     * single-threaded here; create a fresh private lazy-initialized mutex. */
    pthread_mutex_t fresh=PTHREAD_MUTEX_INITIALIZER;
    output_mutex=fresh;
#endif
}
static void install_fork_hook(void)
{
#if defined(__QNXNTO__)
    identity_cache_enabled = pthread_atfork(before_fork, after_fork, reset_child_identity) == 0;
#else
    identity_cache_enabled = pthread_atfork(NULL, NULL, reset_child_identity) == 0;
#endif
}
static void thread_identity(void)
{
    char *out = identity.text;
    APPEND(out, " tid="); out = decimal(out, lti_thread_id());
    APPEND(out, " pid="); out = decimal(out, (uint64_t)getpid());
    identity.length = (unsigned)(out - identity.text);
}

#if defined(__QNXNTO__)
static int format_clock(char *data, size_t capacity)
{
    uint64_t cycles=ClockCycles();
    return snprintf(data, capacity,
        "{\"clock\":\"qnx_cycles\",\"mono_ns\":%llu,\"cycles\":%llu,\"cycles_per_sec\":%llu,\"bracket_cycles\":0}",
        (unsigned long long)cycle_ns(cycles), (unsigned long long)cycles,
        (unsigned long long)cycle_frequency);
}
static void clock_metadata(const char *path)
{
    struct stat status;
    if (fstat(event_fd, &status) || !S_ISREG(status.st_mode)) return;
    char data[320];int size = format_clock(data, sizeof(data));
    if (size <= 0 || size >= (int)sizeof(data)-1) return;
    data[size++] = '\n';
    char *name = malloc(strlen(path) + sizeof(".clock.json"));
    if (!name) return;
    sprintf(name, "%s.clock.json", path);
    int fd = open(name, O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0600);
    free(name);
    if (fd < 0) return;
    (void)write(fd, data, (size_t)size);
    close(fd);
}
static void kernel_clock_metadata(void)
{
    char data[352]="LTI_CLOCK ";
    int size=format_clock(data+10,sizeof(data)-10);
    if (size>0 && size<(int)sizeof(data)-10)
        if (TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT,LTI_QNX_EVENT_ID-1,data)==-1)
            atomic_fetch_add_explicit(&write_errors,1,memory_order_relaxed);
}
#endif

int lti_init(void)
{
    (void)pthread_once(&fork_hook, install_fork_hook);
    if (backend != DISABLED) return 0;
#if defined(__QNXNTO__)
    cycle_frequency=SYSPAGE_ENTRY(qtime)->cycles_per_sec;
    if (!cycle_frequency) { errno=ENOTSUP; return -1; }
#endif
    const char *path = getenv("LTI_EVENT_FILE");
    if (path && path[0]) {
#if defined(__QNXNTO__)
        if (!identity_cache_enabled) { errno=ENOTSUP; return -1; }
#endif
        event_fd = open(path, O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0600);
        if (event_fd < 0) return -1;
        backend = EVENT_FILE;
#if defined(__QNXNTO__)
        clock_metadata(path);
#endif
        return 0;
    }
#if defined(__QNXNTO__)
    /* Insertion only: the SDK never resets/starts/stops the global tracer. */
    backend = QNX_TRACE;
    kernel_clock_metadata();
    return 0;
#else
    event_fd = open("/sys/kernel/tracing/trace_marker", O_WRONLY|O_CLOEXEC);
    if (event_fd < 0) event_fd = open("/sys/kernel/debug/tracing/trace_marker", O_WRONLY|O_CLOEXEC);
    if (event_fd < 0) return -1;
    backend = KERNEL_MARKER;
    return 0;
#endif
}
void lti_shutdown(void)
{
    if (event_fd >= 0) close(event_fd);
    event_fd = -1; backend = DISABLED;
}
uint64_t lti_write_errors(void) { return atomic_load_explicit(&write_errors, memory_order_relaxed); }

void lti_event(lti_phase_t phase, uint64_t job_id, uint64_t resource_id)
{
    if (backend == DISABLED || (unsigned)phase >= sizeof(phases)/sizeof(phases[0])) return;
    int saved_errno = errno;
#if defined(__QNXNTO__)
    if (backend == EVENT_FILE) (void)pthread_mutex_lock(&output_mutex);
#endif
    char message[256], *out = message;
    if (backend == EVENT_FILE || backend == QNX_TRACE) {
        uint64_t timestamp;
#if defined(__QNXNTO__)
        timestamp=cycle_ns(ClockCycles());
#else
        struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now)) {
            atomic_fetch_add_explicit(&write_errors, 1, memory_order_relaxed);
            errno = saved_errno; return;
        }
        timestamp=(uint64_t)now.tv_sec*UINT64_C(1000000000)+(uint64_t)now.tv_nsec;
#endif
        if (!identity.length || !identity_cache_enabled) thread_identity();
        APPEND(out, "LTI_EVENT mono_ns=");
        out = decimal(out, timestamp);
        memcpy(out, identity.text, identity.length); out += identity.length;
        APPEND(out, " job=");
    } else {
        APPEND(out, "LTI job=");
    }
    out = decimal(out, job_id);
    APPEND(out, " phase=");
    memcpy(out, phases[phase].text, phases[phase].length); out += phases[phase].length;
    APPEND(out, " v=1");
    if (backend == KERNEL_MARKER) {
        APPEND(out, " pid="); out = decimal(out, (uint64_t)getpid());
    }
    APPEND(out, " resource="); out = decimal(out, resource_id);
    if (backend == EVENT_FILE) *out++ = '\n';
    int failed = 0;
#if defined(__QNXNTO__)
    if (backend == QNX_TRACE) {
        *out = '\0';
        failed = TraceEvent(_NTO_TRACE_INSERTUSRSTREVENT, LTI_QNX_EVENT_ID, message) == -1;
    } else
#endif
    {
        ssize_t count;
        do { count = write(event_fd, message, (size_t)(out-message)); } while (count < 0 && errno == EINTR);
        failed = count != out-message;
    }
#if defined(__QNXNTO__)
    if (backend == EVENT_FILE) (void)pthread_mutex_unlock(&output_mutex);
#endif
    if (failed) atomic_fetch_add_explicit(&write_errors, 1, memory_order_relaxed);
    errno = saved_errno;
}

int lti_mutex_lock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id)
{
    lti_event(LTI_LOCK_WAIT, job_id, resource_id);
    int result = pthread_mutex_lock(mutex);
    if (result == 0) lti_event(LTI_LOCK_ACQUIRED, job_id, resource_id);
    return result;
}
int lti_mutex_unlock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id)
{
    /* Boundary precedes the actual release, including attempted failed calls. */
    lti_event(LTI_LOCK_RELEASE, job_id, resource_id);
    return pthread_mutex_unlock(mutex);
}
int lti_cond_wait(pthread_cond_t *condition, pthread_mutex_t *mutex,
                  uint64_t condition_id, uint64_t mutex_id, uint64_t job_id)
{
    lti_event(LTI_LOCK_RELEASE, job_id, mutex_id);
    lti_event(LTI_COND_WAIT_BEGIN, job_id, condition_id);
    int result = pthread_cond_wait(condition, mutex);
    lti_event(LTI_COND_WAIT_END, job_id, condition_id);
    lti_event(LTI_LOCK_ACQUIRED, job_id, mutex_id);
    return result;
}
