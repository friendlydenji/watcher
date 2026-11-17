#if defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#define _GNU_SOURCE
#endif
#include "lti/lti.h"

#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

enum { MUTEX_ID = 10, REQUEST_COND_ID = 11, REPLY_COND_ID = 12 };

struct channel {
    pthread_mutex_t mutex;
    pthread_cond_t request;
    pthread_cond_t reply;
    unsigned job_id;
    bool request_ready;
    bool reply_ready;
    bool stop;
};

static void *consumer(void *arg)
{
    struct channel *channel = arg;
    printf("C worker TID=%ld\n", (long)lti_thread_id());
    fflush(stdout);
    for (;;) {
        lti_mutex_lock(&channel->mutex, MUTEX_ID, LTI_NO_JOB);
        while (!channel->request_ready && !channel->stop)
            lti_cond_wait(&channel->request, &channel->mutex,
                          REQUEST_COND_ID, MUTEX_ID, LTI_NO_JOB);
        if (channel->stop) {
            lti_mutex_unlock(&channel->mutex, MUTEX_ID, LTI_NO_JOB);
            break;
        }
        unsigned job_id = channel->job_id;
        channel->request_ready = false;
        lti_mutex_unlock(&channel->mutex, MUTEX_ID, job_id);

        lti_event(LTI_RECEIVE, job_id, 0);
        lti_event(LTI_COMPUTE_BEGIN, job_id, 0);
        volatile unsigned long result = 0;
        for (unsigned long n = 0; n < 1200000; ++n)
            result += n;
        lti_event(LTI_COMPUTE_END, job_id, 0);
        lti_event(LTI_SLEEP_BEGIN, job_id, 0);
        struct timespec pause = { .tv_sec = 0, .tv_nsec = 10000000 };
        nanosleep(&pause, NULL);
        lti_event(LTI_SLEEP_END, job_id, 0);
        lti_event(LTI_DONE, job_id, 0);

        lti_mutex_lock(&channel->mutex, MUTEX_ID, job_id);
        channel->reply_ready = true;
        pthread_cond_signal(&channel->reply);
        lti_mutex_unlock(&channel->mutex, MUTEX_ID, job_id);
        printf("C worker completed job=%u result=%lu\n", job_id, result);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    long count = 5;
    if (argc > 1) {
        char *end = NULL;
        count = strtol(argv[1], &end, 10);
        if (*end != '\0' || count < 1 || count > 100) {
            fprintf(stderr, "usage: %s [jobs: 1..100]\n", argv[0]);
            return 2;
        }
    }
    if (lti_init() != 0)
        fprintf(stderr, "LTI tracing unavailable; demo still runs\n");
    printf("C main PID=%ld TID=%ld jobs=%ld\n",
           (long)getpid(), (long)lti_thread_id(), count);
    fflush(stdout);

    struct channel channel = {
        .mutex = PTHREAD_MUTEX_INITIALIZER,
        .request = PTHREAD_COND_INITIALIZER,
        .reply = PTHREAD_COND_INITIALIZER,
    };
    pthread_t thread;
    if (pthread_create(&thread, NULL, consumer, &channel) != 0) {
        fprintf(stderr, "pthread_create failed\n");
        lti_shutdown();
        return 1;
    }
    for (unsigned job_id = 1; job_id <= (unsigned)count; ++job_id) {
        lti_mutex_lock(&channel.mutex, MUTEX_ID, job_id);
        channel.job_id = job_id;
        channel.reply_ready = false;
        channel.request_ready = true;
        lti_event(LTI_SEND, job_id, 0);
        pthread_cond_signal(&channel.request);
        lti_mutex_unlock(&channel.mutex, MUTEX_ID, job_id);

        lti_mutex_lock(&channel.mutex, MUTEX_ID, job_id);
        while (!channel.reply_ready)
            lti_cond_wait(&channel.reply, &channel.mutex,
                          REPLY_COND_ID, MUTEX_ID, job_id);
        lti_mutex_unlock(&channel.mutex, MUTEX_ID, job_id);
    }

    lti_mutex_lock(&channel.mutex, MUTEX_ID, LTI_NO_JOB);
    channel.stop = true;
    pthread_cond_signal(&channel.request);
    lti_mutex_unlock(&channel.mutex, MUTEX_ID, LTI_NO_JOB);
    pthread_join(thread, NULL);
    pthread_cond_destroy(&channel.request);
    pthread_cond_destroy(&channel.reply);
    pthread_mutex_destroy(&channel.mutex);
    lti_shutdown();
    printf("C main completed=%ld\n", count);
    return 0;
}
