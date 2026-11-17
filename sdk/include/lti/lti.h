#ifndef LTI_LTI_H
#define LTI_LTI_H

#include <pthread.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LTI_SCHEMA_VERSION 1
#ifndef LTI_QNX_EVENT_ID
#define LTI_QNX_EVENT_ID 1020
#endif

#if LTI_QNX_EVENT_ID < 1 || LTI_QNX_EVENT_ID > 1023
#error "LTI_QNX_EVENT_ID must reserve two user event IDs in 0..1023"
#endif

#define LTI_NO_JOB UINT64_C(0)

typedef enum lti_phase {
    LTI_SEND,
    LTI_RECEIVE,
    LTI_DONE,
    LTI_COMPUTE_BEGIN,
    LTI_COMPUTE_END,
    LTI_SLEEP_BEGIN,
    LTI_SLEEP_END,
    LTI_LOCK_WAIT,
    LTI_LOCK_ACQUIRED,
    LTI_LOCK_RELEASE,
    LTI_COND_WAIT_BEGIN,
    LTI_COND_WAIT_END
} lti_phase_t;

/* Initialize before creating threads. LTI_EVENT_FILE selects the unprivileged
 * append-only event-file backend; otherwise Linux trace_marker or QNX user trace events are used. Returns -1
 * if the selected backend cannot open. Recording calls then become no-ops. */
int lti_init(void);
void lti_shutdown(void);
/* Native TID: globally scoped on Linux, scoped to PID on QNX. */
uint64_t lti_thread_id(void);
/* Failed/short writes or failed clock/TraceEvent calls since process start.
 * Success does not prove that the external kernel collector retained events. */
uint64_t lti_write_errors(void);

/* job_id is unique within the process and capture; 0 means no job is known.
 * resource_id identifies an application mutex or condition variable; 0 means
 * no resource applies. */
void lti_event(lti_phase_t phase, uint64_t job_id, uint64_t resource_id);

/* These wrappers perform the pthread operation and record its boundary. They
 * return the same error code as the corresponding pthread function. */
int lti_mutex_lock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id);
int lti_mutex_unlock(pthread_mutex_t *mutex, uint64_t resource_id, uint64_t job_id);
int lti_cond_wait(pthread_cond_t *condition, pthread_mutex_t *mutex,
                  uint64_t condition_id, uint64_t mutex_id, uint64_t job_id);

#ifdef __cplusplus
}
#endif

#endif
