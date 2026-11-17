#define _GNU_SOURCE
#include "lti/lti.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static char event_path[] = "/tmp/watcher-sdk-XXXXXX";
static int check_release;
int __real_pthread_mutex_unlock(pthread_mutex_t *mutex);
int __wrap_pthread_mutex_unlock(pthread_mutex_t *mutex)
{
    if (check_release) {
        /* Deterministic regression: inspect at the exact handoff boundary. */
        FILE *log = fopen(event_path, "r");
        assert(log);
        char line[512], last[512] = "";
        while (fgets(line, sizeof(line), log)) strcpy(last, line);
        fclose(log);
        assert(strstr(last, "phase=lock_release "));
    }
    return __real_pthread_mutex_unlock(mutex);
}

static void *thread_event(void *unused)
{
    (void)unused;
    lti_event(LTI_RECEIVE, 7, 0);
    return NULL;
}

int main(void)
{
    int fd = mkstemp(event_path);
    assert(fd >= 0);
    close(fd);
    assert(setenv("LTI_EVENT_FILE", event_path, 1) == 0);
    assert(lti_init() == 0);
    assert(lti_init() == 0);
    errno = EDOM;
    lti_event(LTI_SEND, 7, 0);
    assert(errno == EDOM);
    lti_event((lti_phase_t)-1, 7, 0);
    lti_event((lti_phase_t)99, 7, 0);
    pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
    assert(lti_mutex_lock(&mutex, 3, 7) == 0);
    check_release = 1;
    assert(lti_mutex_unlock(&mutex, 3, 7) == 0);
    check_release = 0;
    pthread_t thread;
    assert(pthread_create(&thread, NULL, thread_event, NULL) == 0);
    assert(pthread_join(thread, NULL) == 0);
    pid_t child = fork();
    assert(child >= 0);
    if (!child) {
        lti_event(LTI_DONE, 7, 0);
        lti_shutdown();
        _exit(0);
    }
    int status;
    assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    lti_shutdown();
    lti_event(LTI_DONE, 99, 0); /* shutdown is a no-op backend */
    assert(lti_mutex_lock(&mutex, 3, 7) == 0);
    assert(lti_mutex_unlock(&mutex, 3, 7) == 0);
    assert(pthread_mutex_destroy(&mutex) == 0);
    FILE *log = fopen(event_path, "r");
    assert(log);
    char line[512];
    int count = 0, seen_child = 0, seen_thread = 0;
    while (fgets(line, sizeof(line), log)) {
        unsigned long long ns, job, resource;
        long tid, pid;
        char phase[32];
        unsigned version;
        assert(sscanf(line, "LTI_EVENT mono_ns=%llu tid=%ld pid=%ld job=%llu phase=%31s v=%u resource=%llu",
                      &ns, &tid, &pid, &job, phase, &version, &resource) == 7);
        assert(ns > 0 && job == 7 && version == 1);
        if (pid == child) { assert(tid == child); seen_child++; }
        else if (tid != syscall(SYS_gettid)) seen_thread++;
        count++;
    }
    fclose(log);
    assert(count == 6 && seen_child == 1 && seen_thread == 1);
    unlink(event_path);
    assert(setenv("LTI_EVENT_FILE", "/nonexistent/watcher/events", 1) == 0);
    assert(lti_init() == -1);
    lti_event(LTI_SEND, 1, 0);
    lti_shutdown();
    puts("SDK: unlock boundary, schema, thread/fork TIDs, errno, no-op backend passed");
    return 0;
}
