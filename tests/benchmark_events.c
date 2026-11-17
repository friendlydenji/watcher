#define _POSIX_C_SOURCE 200809L
#include "lti/lti.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#if defined(__QNXNTO__)
#include <sys/neutrino.h>
#include <sys/syspage.h>
#endif

static uint64_t now_ns(void)
{
#if defined(__QNXNTO__)
    uint64_t cycles=ClockCycles(), frequency=SYSPAGE_ENTRY(qtime)->cycles_per_sec;
    return cycles/frequency*UINT64_C(1000000000)+(cycles%frequency)*UINT64_C(1000000000)/frequency;
#else
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) abort();
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
#endif
}
struct task { unsigned count; int active; unsigned index; uint64_t elapsed; };
static void *run(void *data)
{
    struct task *task=data;
    uint64_t begin=now_ns();
    for (unsigned i=0;i<task->count;++i)
        lti_event((lti_phase_t)(i%12), (uint64_t)i+1,
                                  i%2 ? UINT64_C(18446744073709551615) : 1);
    task->elapsed=now_ns()-begin;
    return NULL;
}
int main(int argc,char **argv)
{
    unsigned count=argc>1?(unsigned)strtoul(argv[1],NULL,10):200000;
    unsigned threads=argc>2?(unsigned)strtoul(argv[2],NULL,10):1;
    const char *path=argc>3?argv[3]:"/dev/null";
    if (!count||threads<1||threads>64) return 2;
    if (!strcmp(path,"kernel")) unsetenv("LTI_EVENT_FILE");
    else if (setenv("LTI_EVENT_FILE",path,1)) return 1;
    int active=path[0]!='-';
    if(active && lti_init()) {perror("lti_init");return 1;}
    for (unsigned i=0;i<1000;++i) if(active)lti_event(LTI_SEND,i,0);
    pthread_t ids[64];struct task tasks[64];
    uint64_t begin=now_ns();
    for(unsigned i=0;i<threads;++i){tasks[i]=(struct task){count,active,i,0};if(pthread_create(&ids[i],NULL,run,&tasks[i]))return 1;}
    for(unsigned i=0;i<threads;++i)if(pthread_join(ids[i],NULL))return 1;
    uint64_t elapsed=now_ns()-begin,thread_elapsed=0;
    for(unsigned i=0;i<threads;++i)thread_elapsed+=tasks[i].elapsed;
    lti_shutdown();
    printf("{\"events\":%llu,\"threads\":%u,\"elapsed_ns\":%llu,\"ns_per_event\":%.3f,\"events_per_second\":%.3f,\"mean_thread_ns_per_event\":%.3f}\n",
           (unsigned long long)count*threads,threads,(unsigned long long)elapsed,
           (double)elapsed/((double)count*threads),((double)count*threads)*1e9/(double)elapsed,(double)thread_elapsed/((double)count*threads));
    return 0;
}
