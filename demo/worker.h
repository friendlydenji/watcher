#ifndef MIXED_DEMO_WORKER_H
#define MIXED_DEMO_WORKER_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct worker worker_t;

worker_t *worker_start(void);
int worker_submit(worker_t *worker, unsigned job_id);
void worker_stop(worker_t *worker);

#ifdef __cplusplus
}
#endif

#endif
