#define _QNX_SOURCE
#include <sys/trace.h>
#include <sys/neutrino.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t interrupted;
static void on_signal(int signal) { (void)signal; interrupted=1; }
static int trace(int result, const char *operation)
{
    if(result==-1){perror(operation);return -1;}return 0;
}
int main(int argc,char **argv)
{
    if(argc<5){fprintf(stderr,"Usage: %s <seconds:1..120> <new-prefix> <program> [args...]\n",argv[0]);return 2;}
    char *end=NULL;long seconds=strtol(argv[1],&end,10);
    if(!end||*end||seconds<1||seconds>120)return 2;
    char kev[1024],events[1024],diagnostics[1024];
    if(snprintf(kev,sizeof(kev),"%s.kev",argv[2])>=(int)sizeof(kev)||
       snprintf(events,sizeof(events),"%s.events.log",argv[2])>=(int)sizeof(events))return 2;
    if(snprintf(diagnostics,sizeof(diagnostics),"%s.collector.log",argv[2])>=(int)sizeof(diagnostics))return 2;
    /* O_EXCL protects prior captures and makes concurrent invocations fail. */
    int lock=open("/tmp/watcher-qnx-capture.lock",O_WRONLY|O_CREAT|O_EXCL,0600);
    if(lock<0){perror("capture lock (another Watcher capture or stale lock)");return 1;}
    struct stat status;
    if(!stat(kev,&status)||!stat(events,&status)||!stat(diagnostics,&status)){fprintf(stderr,"Capture output exists; use a new prefix\n");close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    /* QNX tracing is global. Refuse an existing logger, including third-party
     * captures. pidin -p returns success even without matches, inspect output. */
    FILE *check=popen("pidin -p tracelogger ar 2>/dev/null","r");
    char line[2048];int busy=0;
    if(!check){close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    while(fgets(line,sizeof(line),check))if(strstr(line,"tracelogger"))busy=1;
    int probe_status=pclose(check);
    if(probe_status!=0){fprintf(stderr,"Unable to inspect collectors with pidin; refusing tracing changes\n");close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    if(busy){fprintf(stderr,"tracelogger already running; refusing global tracing changes\n");close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    int gate[2];if(pipe(gate)){perror("pipe");close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    pid_t app=fork();
    if(!app){
        close(gate[1]);close(lock);char go;
        if(read(gate[0],&go,1)!=1)_exit(125);
        close(gate[0]);
        const char *mode=getenv("WATCHER_QNX_BACKEND");
        if(mode && !strcmp(mode,"kernel"))unsetenv("LTI_EVENT_FILE");
        else if(setenv("LTI_EVENT_FILE",events,1))_exit(126);
        execvp(argv[3],argv+3);perror("exec app");_exit(127);
    }
    close(gate[0]);
    if(app<0){perror("fork");close(gate[1]);close(lock);unlink("/tmp/watcher-qnx-capture.lock");return 1;}
    pid_t logger=-1;int rc=1,app_status=0,logger_status=0;
    signal(SIGINT,on_signal);signal(SIGTERM,on_signal);
    if(trace(TraceEvent(_NTO_TRACE_STOP),"TraceEvent STOP")||
       trace(TraceEvent(_NTO_TRACE_DELALLCLASSES),"DELALLCLASSES")||
       trace(TraceEvent(_NTO_TRACE_ADDCLASS,_NTO_TRACE_THREAD),"ADD THREAD")||
       trace(TraceEvent(_NTO_TRACE_ADDCLASS,_NTO_TRACE_USER),"ADD USER")||
       trace(TraceEvent(_NTO_TRACE_SETCLASSPID,_NTO_TRACE_THREAD,app),"SET THREAD PID"))goto cleanup;
    logger=fork();
    if(!logger){
        close(gate[1]);close(lock);
        int log=open(diagnostics,O_WRONLY|O_CREAT|O_EXCL,0600);
        if(log<0)_exit(126);
        dup2(log,STDOUT_FILENO);dup2(log,STDERR_FILENO);close(log);
        execlp("tracelogger","tracelogger","-F0","-n0","-D1","-b","256","-k","256","-s",argv[1],"-f",kev,(char*)NULL);perror("exec tracelogger");_exit(127);}
    if(logger<0){perror("fork logger");goto cleanup;}
    struct timespec delay={0,200000000};nanosleep(&delay,NULL);
    if(waitpid(logger,&logger_status,WNOHANG)==logger){logger=-1;fprintf(stderr,"tracelogger exited before app started\n");goto cleanup;}
    /* tracelogger initialization may configure event classes; apply our
     * process filter again after it is ready, before releasing the app. */
    if(trace(TraceEvent(_NTO_TRACE_DELALLCLASSES),"DELALLCLASSES ready")||
       trace(TraceEvent(_NTO_TRACE_ADDCLASS,_NTO_TRACE_THREAD),"ADD THREAD ready")||
       trace(TraceEvent(_NTO_TRACE_ADDCLASS,_NTO_TRACE_USER),"ADD USER ready")||
       trace(TraceEvent(_NTO_TRACE_SETCLASSPID,_NTO_TRACE_THREAD,app),"SET PID ready")||
       trace(TraceEvent(_NTO_TRACE_START),"START"))goto cleanup;
    printf("WATCHER_CAPTURE pid=%ld kev=%s events=%s\n",(long)app,kev,events);fflush(stdout);
    if(write(gate[1],"1",1)!=1)goto cleanup;
    close(gate[1]);gate[1]=-1;
    while(waitpid(app,&app_status,0)<0){if(errno!=EINTR||interrupted)goto cleanup;}
    app=-1;
    rc=WIFEXITED(app_status)?WEXITSTATUS(app_status):128+WTERMSIG(app_status);
cleanup:
    (void)TraceEvent(_NTO_TRACE_STOP);
    (void)TraceEvent(_NTO_TRACE_FLUSHBUFFER);
    if(gate[1]>=0)close(gate[1]);
    if(app>0){kill(app,SIGTERM);waitpid(app,NULL,0);}
    if(logger>0){kill(logger,SIGINT);while(waitpid(logger,&logger_status,0)<0&&errno==EINTR){}}
    FILE *messages=fopen(diagnostics,"r");
    if(messages){
        while(fgets(line,sizeof(line),messages)){
            if(strstr(line,"dropping buffers")){
                fprintf(stderr,"WATCHER_CAPTURE_LOSS: %s",line);
                if(!rc)rc=3;
            }else if(strstr(line,"not keeping up")){
                fprintf(stderr,"WATCHER_CAPTURE_BACKLOG: %s",line);
            }
        }
        fclose(messages);
    }
    close(lock);unlink("/tmp/watcher-qnx-capture.lock");
    if(interrupted)return 130;
    if(!rc)printf("WATCHER_COMPLETE %s\n",argv[2]);
    return rc;
}
