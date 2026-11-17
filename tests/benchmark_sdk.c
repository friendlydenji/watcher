#define _POSIX_C_SOURCE 200809L
#include "lti/lti.h"
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec * 1e9 + t.tv_nsec;
}
int main(void)
{
    /* /dev/null isolates formatting + syscall cost; not disk or tracefs cost. */
    if (setenv("LTI_EVENT_FILE", "/dev/null", 1) || lti_init()) return 1;
    const int count = 500000;
    for (int i = 0; i < 1000; i++) lti_event(LTI_SEND, (uint64_t)i, 0);
    double begin = now_ns();
    for (int i = 0; i < count; i++) lti_event(LTI_SEND, (uint64_t)i, 0);
    double elapsed = now_ns() - begin;
    lti_shutdown();
    printf("%d events, %.1f ns/event (/dev/null; single thread; not disk/tracefs)\n",
           count, elapsed / count);
    return 0;
}
