#if defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#define _POSIX_C_SOURCE 200809L
#endif
#include "lti/lti.h"
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready=PTHREAD_COND_INITIALIZER;
static pthread_cond_t finished=PTHREAD_COND_INITIALIZER;
static uint64_t current;
static int available,completed,stop;
static void *worker(void *unused)
{
    (void)unused;
    for(;;){
        pthread_mutex_lock(&mutex);
        while(!available&&!stop)pthread_cond_wait(&ready,&mutex);
        if(stop){pthread_mutex_unlock(&mutex);break;}
        uint64_t job=current;available=0;
        lti_event(LTI_RECEIVE,job,0);
        pthread_mutex_unlock(&mutex);
        struct timespec delay={0,1000000};nanosleep(&delay,NULL);
        lti_event(LTI_DONE,job,0);
        pthread_mutex_lock(&mutex);completed=1;pthread_cond_signal(&finished);pthread_mutex_unlock(&mutex);
    }
    return NULL;
}
int main(int argc,char **argv)
{
    unsigned count=argc>1?(unsigned)strtoul(argv[1],NULL,10):20;
    if(!count||count>100000)return 2;
    if(lti_init()){perror("lti_init");return 1;}
    pthread_t thread;if(pthread_create(&thread,NULL,worker,NULL))return 1;
    for(unsigned i=1;i<=count;++i){
        pthread_mutex_lock(&mutex);current=i;available=1;completed=0;
        lti_event(LTI_SEND,i,0);pthread_cond_signal(&ready);
        while(!completed)pthread_cond_wait(&finished,&mutex);
        pthread_mutex_unlock(&mutex);
    }
    pthread_mutex_lock(&mutex);stop=1;pthread_cond_signal(&ready);pthread_mutex_unlock(&mutex);
    pthread_join(thread,NULL);lti_shutdown();
    printf("JOB_ONLY completed=%u write_errors=%llu\n",count,(unsigned long long)lti_write_errors());
    return 0;
}
