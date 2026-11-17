#define _GNU_SOURCE
#include "lti/lti.h"

#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#if !defined(__QNXNTO__)
#include <sys/syscall.h>
#endif
#include <time.h>
#include <unistd.h>

static int event_fd = -1;
static int file_backend = 0;
static _Thread_local long cached_tid;
static int tid_cache_enabled;
static pthread_once_t fork_hook = PTHREAD_ONCE_INIT;

static void reset_child_tid(void)
{
    cached_tid = 0;
}

static void install_fork_hook(void)
{
    /* The calling thread survives fork(), but its Linux TID changes. */
    tid_cache_enabled = pthread_atfork(NULL, NULL, reset_child_tid) == 0;
}

static const char *const phase_names[] = {
    "send", "receive", "done", "compute_begin", "compute_end",
    "sleep_begin", "sleep_end", "lock_wait", "lock_acquired",
    "lock_release", "cond_wait_begin", "cond_wait_end"
};

int lti_init(void)
{
    (void)pthread_once(&fork_hook, install_fork_hook);
    if (event_fd >= 0)
        return 0;
    const char *path = getenv("LTI_EVENT_FILE");
    if (path && path[0]) {
        event_fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600);
        file_backend = 1;
    } else {
        event_fd = open("/sys/kernel/tracing/trace_marker", O_WRONLY | O_CLOEXEC);
        if (event_fd < 0)
            event_fd = open("/sys/kernel/debug/tracing/trace_marker", O_WRONLY | O_CLOEXEC);
        file_backend = 0;
    }
    return event_fd >= 0 ? 0 : -1;
}

void lti_shutdown(void)
{
    if (event_fd >= 0)
        close(event_fd);
    event_fd = -1;
    file_backend = 0;
}

void lti_event(lti_phase_t phase, uint64_t job_id, uint64_t resource_id)
{
    if (event_fd < 0 || phase < 0 ||
        (unsigned)phase >= sizeof(phase_names) / sizeof(phase_names[0]))
        return;
    int saved_errno = errno;
    char message[192];
    int length;
    if (file_backend) {
        struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
            errno = saved_errno;
            return;
        }
        if (!cached_tid || !tid_cache_enabled)
            #if defined(__QNXNTO__)
            cached_tid = (long)pthread_self();
#else
            cached_tid = syscall(SYS_gettid);
#endif
        uint64_t mono_ns = (uint64_t)now.tv_sec * UINT64_C(1000000000) +
                           (uint64_t)now.tv_nsec;
        length = snprintf(message, sizeof(message),
                          "LTI_EVENT mono_ns=%" PRIu64 " tid=%ld pid=%ld job=%" PRIu64
                          " phase=%s v=%u resource=%" PRIu64 "\n",
                          mono_ns, cached_tid, (long)getpid(), job_id,
                          phase_names[phase], LTI_SCHEMA_VERSION, resource_id);
    } else {
        length = snprintf(message, sizeof(message),
                          "LTI job=%" PRIu64 " phase=%s v=%u pid=%ld resource=%" PRIu64,
                          job_id, phase_names[phase], LTI_SCHEMA_VERSION,
                          (long)getpid(), resource_id);
    }
    if (length > 0 && length < (int)sizeof(message)) {
        ssize_t written = write(event_fd, message, (size_t)length);
        (void)written;
    }
    errno = saved_errno;
}

int lti_mutex_lock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id)
{
    lti_event(LTI_LOCK_WAIT, job_id, resource_id);
    int result = pthread_mutex_lock(mutex);
    if (result == 0)
        lti_event(LTI_LOCK_ACQUIRED, job_id, resource_id);
    return result;
}

int lti_mutex_unlock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id)
{
    /* Emit while ownership still prevents the next holder from recording its
     * acquisition. This is an attempted release if pthread rejects the call. */
    lti_event(LTI_LOCK_RELEASE, job_id, resource_id);
    return pthread_mutex_unlock(mutex);
}

int lti_cond_wait(pthread_cond_t *condition, pthread_mutex_t *mutex,
                  uint64_t condition_id, uint64_t mutex_id, uint64_t job_id)
{
    /* pthread_cond_wait releases and reacquires mutex internally. The markers
     * surround that call; cond_wait includes wakeup and mutex reacquisition. */
    lti_event(LTI_LOCK_RELEASE, job_id, mutex_id);
    lti_event(LTI_COND_WAIT_BEGIN, job_id, condition_id);
    int result = pthread_cond_wait(condition, mutex);
    lti_event(LTI_COND_WAIT_END, job_id, condition_id);
    lti_event(LTI_LOCK_ACQUIRED, job_id, mutex_id);
    return result;
}
