#if defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#define _GNU_SOURCE
#endif
#include "worker.h"
#include "lti/lti.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

struct worker {
    pthread_t thread;
    pthread_mutex_t mutex;
    pthread_cond_t ready;
    struct job *head;
    struct job *tail;
    unsigned processed;
    bool stopping;
};

struct job {
    unsigned id;
    struct job *next;
};

enum { RESOURCE_QUEUE_MUTEX = 1, RESOURCE_READY_COND = 2 };

static void *worker_main(void *arg)
{
    worker_t *worker = arg;
    printf("worker TID=%ld\n", (long)lti_thread_id());
    fflush(stdout);

    for (;;) {
        lti_mutex_lock(&worker->mutex, RESOURCE_QUEUE_MUTEX, LTI_NO_JOB);
        while (worker->head == NULL && !worker->stopping) {
            lti_cond_wait(&worker->ready, &worker->mutex,
                          RESOURCE_READY_COND, RESOURCE_QUEUE_MUTEX, LTI_NO_JOB);
        }
        if (worker->head == NULL && worker->stopping) {
            lti_mutex_unlock(&worker->mutex, RESOURCE_QUEUE_MUTEX, LTI_NO_JOB);
            break;
        }
        struct job *job = worker->head;
        worker->head = job->next;
        if (worker->head == NULL)
            worker->tail = NULL;
        lti_mutex_unlock(&worker->mutex, RESOURCE_QUEUE_MUTEX, job->id);
        lti_event(LTI_RECEIVE, job->id, 0);

        lti_event(LTI_COMPUTE_BEGIN, job->id, 0);
        volatile unsigned long checksum = 0;
        for (unsigned long i = 0; i < 3000000; ++i)
            checksum += i;
        lti_event(LTI_COMPUTE_END, job->id, 0);
        lti_event(LTI_SLEEP_BEGIN, job->id, 0);
        usleep(20000);
        lti_event(LTI_SLEEP_END, job->id, 0);
        lti_event(LTI_DONE, job->id, 0);
        free(job);

        ++worker->processed;
        unsigned processed = worker->processed;
        if (processed % 10 == 0)
            printf("worker processed=%u checksum=%lu\n", processed, checksum);
    }
    return NULL;
}

worker_t *worker_start(void)
{
    worker_t *worker = calloc(1, sizeof(*worker));
    if (!worker)
        return NULL;
    if (pthread_mutex_init(&worker->mutex, NULL) != 0) {
        free(worker);
        return NULL;
    }
    if (pthread_cond_init(&worker->ready, NULL) != 0) {
        pthread_mutex_destroy(&worker->mutex);
        free(worker);
        return NULL;
    }
    if (pthread_create(&worker->thread, NULL, worker_main, worker) != 0) {
        pthread_cond_destroy(&worker->ready);
        pthread_mutex_destroy(&worker->mutex);
        free(worker);
        return NULL;
    }
    return worker;
}

int worker_submit(worker_t *worker, unsigned job_id)
{
    struct job *job = malloc(sizeof(*job));
    if (!job)
        return -1;
    job->id = job_id;
    job->next = NULL;
    lti_mutex_lock(&worker->mutex, RESOURCE_QUEUE_MUTEX, job_id);
    if (worker->stopping) {
        lti_mutex_unlock(&worker->mutex, RESOURCE_QUEUE_MUTEX, job_id);
        free(job);
        return -1;
    }
    if (worker->tail)
        worker->tail->next = job;
    else
        worker->head = job;
    worker->tail = job;
    lti_event(LTI_SEND, job_id, 0);
    pthread_cond_signal(&worker->ready);
    lti_mutex_unlock(&worker->mutex, RESOURCE_QUEUE_MUTEX, job_id);
    return 0;
}

void worker_stop(worker_t *worker)
{
    if (!worker)
        return;
    lti_mutex_lock(&worker->mutex, RESOURCE_QUEUE_MUTEX, LTI_NO_JOB);
    worker->stopping = true;
    pthread_cond_signal(&worker->ready);
    lti_mutex_unlock(&worker->mutex, RESOURCE_QUEUE_MUTEX, LTI_NO_JOB);
    pthread_join(worker->thread, NULL);
    printf("worker completed=%u\n", worker->processed);
    pthread_cond_destroy(&worker->ready);
    pthread_mutex_destroy(&worker->mutex);
    free(worker);
}
