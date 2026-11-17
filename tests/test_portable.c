#if defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#define _POSIX_C_SOURCE 200809L
#endif
#include "lti/lti.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
static void *emit(void *unused)
{
    (void)unused;
    for(unsigned i=0;i<1000;i++)lti_event((lti_phase_t)(i%12),UINT64_MAX,UINT64_MAX);
    return NULL;
}
int main(void)
{
    char path[]="/tmp/watcher-portable-XXXXXX";
    int fd=mkstemp(path);assert(fd>=0);close(fd);
    assert(setenv("LTI_EVENT_FILE",path,1)==0);assert(lti_init()==0);
    errno=EDOM;lti_event(LTI_SEND,0,0);assert(errno==EDOM);
    lti_event((lti_phase_t)-1,1,1);lti_event((lti_phase_t)99,1,1);
    pthread_t threads[4];for(unsigned i=0;i<4;i++)assert(!pthread_create(threads+i,NULL,emit,NULL));
    for(unsigned i=0;i<4;i++)assert(!pthread_join(threads[i],NULL));
    pid_t child=fork();assert(child>=0);
    if(!child){lti_event(LTI_DONE,7,8);lti_shutdown();_exit(0);}
    int status;assert(waitpid(child,&status,0)==child);assert(WIFEXITED(status)&&WEXITSTATUS(status)==0);
    lti_shutdown();assert(lti_write_errors()==0);
    FILE *file=fopen(path,"r");assert(file);char line[512],phase[32];unsigned records=0,child_records=0;
    while(fgets(line,sizeof(line),file)){
        unsigned long long time,tid,pid,job,resource;unsigned version;
        assert(sscanf(line,"LTI_EVENT mono_ns=%llu tid=%llu pid=%llu job=%llu phase=%31s v=%u resource=%llu",&time,&tid,&pid,&job,phase,&version,&resource)==7);
        assert(time>0&&tid>0&&version==1);
        if(pid==(unsigned long long)child){assert(job==7&&resource==8);child_records++;}
        else if(records)assert(job==UINT64_MAX&&resource==UINT64_MAX);
        records++;
    }
    fclose(file);assert(records==4002&&child_records==1);unlink(path);
    char metadata[256];snprintf(metadata,sizeof(metadata),"%s.clock.json",path);unlink(metadata);
    printf("PORTABLE_TEST records=%u child_records=%u errors=%llu\n",records,child_records,(unsigned long long)lti_write_errors());
    return 0;
}
