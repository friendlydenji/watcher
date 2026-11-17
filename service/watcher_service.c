/* Target-resident, read-only HTTP dashboard. No Python, shell command API or
 * SDK networking. QNX reader uses the SDK traceparser and follows complete
 * 16-byte slots once; HTTP responses are bounded snapshots of retained data. */
#if defined(__QNXNTO__)
#define _QNX_SOURCE
#else
#define _POSIX_C_SOURCE 200809L
#endif
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/time.h>
#include <sys/select.h>
#include <spawn.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <signal.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#ifdef __QNXNTO__
#include <sys/traceparser.h>
#include "lti/lti.h"
#include <sys/syspage.h>
#endif

#define RECORDS 20000
#define THREADS 1024
#define JSON_LIMIT (16u*1024u*1024u)
typedef struct { uint64_t ns,job,resource; unsigned pid,tid,track,cpu; char phase[32],state[16]; } Record;
typedef struct { unsigned pid,tid; } Identity;
static Record events[RECORDS],states[RECORDS];
static size_t nevents,nstates;static uint64_t total_events,total_states;
static Identity identities[THREADS];static unsigned nthreads;
static unsigned char cpus[256];
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static volatile sig_atomic_t stopping;
static int active,finished,exit_code,failed,limited,waiting;
#ifdef __QNXNTO__
static int parser_failed;
#endif
extern char **environ;
static char error_message[256],kev[2048],prefix[2048],session_name[128];
static const char *ui_dir="ui",*capture_dir="traces",*listen_ip="0.0.0.0",*helper="./watcher-qnx-capture",*fixture=NULL,*replay_kev=NULL;
static unsigned app_pid,port=8765;static const char *seconds="0";static char **program;
static pid_t capture_pid=-1;static uint64_t frequency;
static void on_signal(int sig){(void)sig;stopping=1;}
static void pause_ms(unsigned ms){struct timespec t={ms/1000,(long)(ms%1000)*1000000};nanosleep(&t,NULL);}
static void fail(const char *message){pthread_mutex_lock(&mutex);failed=1;snprintf(error_message,sizeof(error_message),"%s",message);pthread_mutex_unlock(&mutex);}
static unsigned track(unsigned pid,unsigned tid){
    for(unsigned i=0;i<nthreads;i++)if(identities[i].pid==pid&&identities[i].tid==tid)return i+1;
    if(nthreads==THREADS){limited=1;return 0;}
    identities[nthreads]=(Identity){pid,tid};return ++nthreads;
}
static void append(Record *records,size_t *count,uint64_t *total,Record record){
    records[*total%RECORDS]=record;(*total)++;if(*count<RECORDS)(*count)++;else limited=1;
}
static void marker(const char *text){
    Record r={0};unsigned version;
    if(sscanf(text,"LTI_EVENT mono_ns=%"SCNu64" tid=%u pid=%u job=%"SCNu64" phase=%31s v=%u resource=%"SCNu64,
              &r.ns,&r.tid,&r.pid,&r.job,r.phase,&version,&r.resource)!=7||version!=1||!r.pid||!r.tid)return;
    if(app_pid&&r.pid!=app_pid)return;
    pthread_mutex_lock(&mutex);r.track=track(r.pid,r.tid);
    if(r.track)append(events,&nevents,&total_events,r);
    pthread_mutex_unlock(&mutex);
}
static void transition(uint64_t ns,unsigned pid,unsigned tid,unsigned cpu,const char *state){
    Record r={0};r.ns=ns;r.pid=pid;r.tid=tid;r.cpu=cpu;snprintf(r.state,sizeof(r.state),"%s",state);
    pthread_mutex_lock(&mutex);r.track=track(pid,tid);
    if(r.track){append(states,&nstates,&total_states,r);if(!strcmp(state,"running")&&cpu<sizeof(cpus))cpus[cpu]=1;}
    pthread_mutex_unlock(&mutex);
}

#ifdef __QNXNTO__
static int state_callback(struct traceparser_state *parser,void *user,unsigned header,unsigned low,unsigned *buffer,unsigned len){
    (void)low;unsigned state=*(unsigned*)user;
    if(len<2||(app_pid&&buffer[0]!=app_pid))return 0;
    const uint64_t *clock=traceparser_get_info(parser,_TRACEPARSER_INFO_CLK,NULL);
    if(!clock){fail("traceparser did not provide a full cycle timestamp");return 0;}
    uint64_t cycles=*clock,ns=cycles/frequency*UINT64_C(1000000000)+(cycles%frequency)*UINT64_C(1000000000)/frequency;
    const char *kind=state==STATE_RUNNING?"running":state==STATE_READY?"runnable":state==STATE_DEAD||state==UINT32_MAX?"ended":state==STATE_STOPPED?"other":"sleeping";
    transition(ns,buffer[0],buffer[1],_NTO_TRACE_GETCPU(header),kind);return 0;
}
static int user_callback(struct traceparser_state *parser,void *user,unsigned header,unsigned low,unsigned *buffer,unsigned len){
    (void)parser;(void)user;(void)low;
    if(_NTO_TRACE_GETEVENT(header)!=LTI_QNX_EVENT_ID)return 0;
    char text[1025];size_t bytes=(size_t)len*sizeof(*buffer);if(bytes>=sizeof(text))bytes=sizeof(text)-1;
    memcpy(text,buffer,bytes);text[bytes]=0;
    char *begin=strstr(text,"LTI_EVENT ");if(begin)marker(begin);return 0;
}
/* Keep the supported traceparser() call alive at temporary EOF. Its cleanup
 * frees event-reordering storage, so feeding one_event() after EOF is invalid.
 * Only this reader thread's static libtraceparser fread calls are adapted;
 * HTTP/static-file reads retain normal stdio behavior. */
static _Thread_local int follow_reads;
static int incomplete_stream;
extern size_t __real_fread(void *,size_t,size_t,FILE *);
size_t __wrap_fread(void *data,size_t size,size_t count,FILE *stream){
    if(!follow_reads)return __real_fread(data,size,count,stream);
    if(!size||!count||count>SIZE_MAX/size)return 0;
    size_t wanted=size*count,used=0;
    while(used<wanted){
        used+=__real_fread((unsigned char*)data+used,1,wanted-used,stream);
        if(used==wanted)break;
        if(ferror(stream)){fail("Cannot read growing kernel trace");break;}
        clearerr(stream);
        pthread_mutex_lock(&mutex);int done=finished;pthread_mutex_unlock(&mutex);
        if(done){if(used)incomplete_stream=1;break;}
        pause_ms(50);
    }
    return used/size;
}
static void read_kernel(void){
    static char header[65537];int ready=0;
    for(;;){
        FILE *input=fopen(kev,"rb");
        if(input){
            size_t used=fread(header,1,sizeof(header)-1,input);header[used]=0;
            char *end=strstr(header,"TRACE_HEADER_END::"),*hz=strstr(header,"TRACE_CYCLES_PER_SEC::"),*length=strstr(header,"TRACE_SYSPAGE_LEN::");
            struct stat status;
            if(end&&hz&&length&&!fstat(fileno(input),&status)){
                uint64_t cycles_per_second=strtoull(hz+strlen("TRACE_CYCLES_PER_SEC::"),NULL,10);
                unsigned long syspage=strtoul(length+strlen("TRACE_SYSPAGE_LEN::"),NULL,10);
                size_t metadata=(size_t)(end-header)+strlen("TRACE_HEADER_END::")+syspage;
                if(cycles_per_second&&syspage<=1024*1024&&status.st_size>=(off_t)metadata){
                    pthread_mutex_lock(&mutex);frequency=cycles_per_second;pthread_mutex_unlock(&mutex);ready=1;
                }
            }
            fclose(input);
        }
        if(!replay_kev&&!app_pid){
            char log[2200],line[1024];snprintf(log,sizeof(log),"%s.app.log",prefix);FILE *messages=fopen(log,"r");
            if(messages){while(fgets(line,sizeof(line),messages))if(sscanf(line,"WATCHER_CAPTURE pid=%u",&app_pid)==1)break;fclose(messages);}
        }
        if(ready&&(replay_kev||app_pid))break;
        pthread_mutex_lock(&mutex);int done=finished;pthread_mutex_unlock(&mutex);
        if(done){fail("Collector did not provide a complete kernel trace header");return;}
        pause_ms(100);
    }
    struct traceparser_state *parser=traceparser_init(NULL);unsigned state_ids[STATE_MAX+1];int bad=parser?0:1;
    if(parser){
        for(unsigned i=0;i<STATE_MAX;i++){state_ids[i]=i;bad|=traceparser_cs(parser,&state_ids[i],state_callback,_NTO_TRACE_THREAD,1u<<i);}
        state_ids[STATE_MAX]=UINT32_MAX;
        bad|=traceparser_cs(parser,&state_ids[STATE_MAX],state_callback,_NTO_TRACE_THREAD,_NTO_TRACE_THDESTROY);
        bad|=traceparser_cs(parser,NULL,user_callback,_NTO_TRACE_USER,LTI_QNX_EVENT_ID);
    }
    if(bad){if(parser)traceparser_destroy(&parser);fail("Cannot initialize traceparser callbacks");return;}
    fprintf(stderr,"Reader ready: cycles_per_sec=%"PRIu64"\n",frequency);
    follow_reads=1;int result=traceparser(parser,NULL,kev);follow_reads=0;
    if(result||incomplete_stream){parser_failed=1;fail("Invalid or incomplete kernel event stream");}
    traceparser_destroy(&parser);
}

#endif
/* Text input is for deterministic tests and offline fixtures only, explicitly
 * selected with --fixture. It never generates scheduler observations. */
static void read_fixture(void){
    FILE *f=fopen(fixture,"r");if(!f){fail("Cannot open fixture");return;}
    char line[2048];
    while(!stopping){
        if(fgets(line,sizeof(line),f)){
            uint64_t ns;unsigned pid,tid,cpu;char state[16];
            if(sscanf(line,"STATE %"SCNu64" %u %u %u %15s",&ns,&pid,&tid,&cpu,state)==5)transition(ns,pid,tid,cpu,state);
            else marker(line);
        }else {clearerr(f);pthread_mutex_lock(&mutex);int done=finished;pthread_mutex_unlock(&mutex);if(done)break;pause_ms(50);}
    }fclose(f);
}
static void *reader(void *unused){(void)unused;
    if(fixture)read_fixture();
#ifdef __QNXNTO__
    else read_kernel();
#endif
    pthread_mutex_lock(&mutex);active=0;finished=1;pthread_mutex_unlock(&mutex);return NULL;
}
static void *collector(void *unused){(void)unused;
    pthread_mutex_lock(&mutex);while(waiting&&!stopping){pthread_mutex_unlock(&mutex);pause_ms(50);pthread_mutex_lock(&mutex);}pthread_mutex_unlock(&mutex);
    if(stopping){pthread_mutex_lock(&mutex);finished=1;pthread_mutex_unlock(&mutex);return NULL;}
    if(replay_kev){pthread_mutex_lock(&mutex);finished=1;pthread_mutex_unlock(&mutex);return NULL;}
    if(fixture){pthread_mutex_lock(&mutex);active=1;pthread_mutex_unlock(&mutex);return NULL;}
    char log[2200];snprintf(log,sizeof(log),"%s.app.log",prefix);
    int fd=open(log,O_WRONLY|O_CREAT|O_EXCL,0600);
    size_t count=0;while(program[count])count++;
    char **args=calloc(count+4,sizeof(*args));
    pid_t pid=-1;
    if(fd>=0&&args){
        args[0]=(char*)helper;args[1]=(char*)seconds;args[2]=prefix;
        for(size_t i=0;i<count;i++)args[i+3]=program[i];
        posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
        posix_spawn_file_actions_adddup2(&actions,fd,STDOUT_FILENO);
        posix_spawn_file_actions_adddup2(&actions,fd,STDERR_FILENO);
        if(fd>2)posix_spawn_file_actions_addclose(&actions,fd);
        int result=posix_spawn(&pid,helper,&actions,NULL,args,environ);
        posix_spawn_file_actions_destroy(&actions);if(result){errno=result;perror("spawn helper");pid=-1;}
    }
    if(fd>=0)close(fd);
    free(args);
    pthread_mutex_lock(&mutex);capture_pid=pid;active=pid>0;pthread_mutex_unlock(&mutex);
    if(pid<0){fail("Cannot launch capture helper");pthread_mutex_lock(&mutex);finished=1;pthread_mutex_unlock(&mutex);return NULL;}
    int status;
    for(;;){pid_t r=waitpid(pid,&status,WNOHANG);if(r==pid)break;if(r<0&&errno!=EINTR){status=1<<8;break;}if(stopping)kill(pid,SIGTERM);pause_ms(100);}
    pthread_mutex_lock(&mutex);exit_code=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);capture_pid=-1;finished=1;pthread_mutex_unlock(&mutex);
    if(exit_code)fail(exit_code==3?"Collector reported dropped buffers":"Capture failed; inspect .app.log and .collector.log");
    return NULL;
}

typedef struct { char *data;size_t len,capacity;int bad; } Buffer;
static void add(Buffer *b,const char *format,...){
    if(b->bad)return;
    for(;;){
        va_list args;va_start(args,format);int n=vsnprintf(b->data?b->data+b->len:NULL,b->capacity-b->len,format,args);va_end(args);
        if(n<0){b->bad=1;return;}
        if((size_t)n<b->capacity-b->len){b->len+=(size_t)n;return;}
        size_t cap=b->capacity?b->capacity*2:4096;if(cap<b->len+(size_t)n+1)cap=b->len+(size_t)n+1;
        if(cap>JSON_LIMIT){b->bad=1;return;}char *data=realloc(b->data,cap);if(!data){b->bad=1;return;}b->data=data;b->capacity=cap;
    }
}
static void string(Buffer *b,const char *s){add(b,"\"");for(const unsigned char *p=(const unsigned char*)s;*p;p++){if(*p=='"'||*p=='\\')add(b,"\\%c",*p);else if(*p<32)add(b,"\\u%04x",*p);else add(b,"%c",*p);}add(b,"\"");}
static void record_json(Buffer *b,const Record *r,int state){
    add(b,"{\"time_s\":\"%"PRIu64".%09"PRIu64"\",\"pid\":%u,\"tid\":%u,\"track_id\":%u",r->ns/1000000000,r->ns%1000000000,r->pid,r->tid,r->track);
    if(state){add(b,",\"cpu\":%u,\"state\":",r->cpu);string(b,r->state);}
    else{add(b,",\"job_id\":\"%"PRIu64"\",\"resource_id\":\"%"PRIu64"\",\"phase\":",r->job,r->resource);string(b,r->phase);}
    add(b,"}");
}
static Buffer snapshot(void){
    Buffer b={0};pthread_mutex_lock(&mutex);
    add(&b,"{\"service\":\"watcher-qnx\",\"platform\":\"qnx\",\"name\":\"%s\",\"active\":%s,\"phase\":\"%s\",\"app_exit_code\":%d,\"history_limited\":%s,\"event_loss_reported\":%s,\"error\":",session_name,active?"true":"false",waiting?"waiting":failed?"failed":active?"recording":finished?"complete":"starting",exit_code,limited?"true":"false",failed?"true":"false");
    if(failed)string(&b,error_message);else add(&b,"null");
    add(&b,",\"clock_resolution_ns\":%"PRIu64",\"events\":[",frequency?(UINT64_C(1000000000)+frequency-1)/frequency:0);
    for(size_t i=0;i<nevents;i++){if(i)add(&b,",");record_json(&b,&events[(total_events-nevents+i)%RECORDS],0);}
    add(&b,"],\"transitions\":[");for(size_t i=0;i<nstates;i++){if(i)add(&b,",");record_json(&b,&states[(total_states-nstates+i)%RECORDS],1);}
    add(&b,"],\"threads\":[");for(unsigned i=0;i<nthreads;i++){if(i)add(&b,",");add(&b,"{\"pid\":%u,\"tid\":%u,\"track_id\":%u}",identities[i].pid,identities[i].tid,i+1);}
    add(&b,"],\"thread_ids\":[");for(unsigned i=0;i<nthreads;i++)add(&b,"%s%u",i?",":"",i+1);
    add(&b,"],\"cpus\":[");int comma=0;for(unsigned i=0;i<sizeof(cpus);i++)if(cpus[i]){add(&b,"%s%u",comma?",":"",i);comma=1;}
    add(&b,"],\"scheduler\":[],\"jobs\":[]}");pthread_mutex_unlock(&mutex);return b;
}
static int send_all(int fd,const char *data,size_t len){while(len){ssize_t n=send(fd,data,len,0);if(n<0&&errno==EINTR)continue;if(n<=0)return -1;data+=n;len-=(size_t)n;}return 0;}
static void response(int fd,unsigned status,const char *type,const char *data,size_t len){
    char header[512];int n=snprintf(header,sizeof(header),"HTTP/1.1 %u %s\r\nContent-Type: %s\r\nContent-Length: %zu\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nConnection: close\r\n\r\n",status,status==200?"OK":status==404?"Not Found":"Error",type,len);
    if(n>0&&send_all(fd,header,(size_t)n)==0)send_all(fd,data,len);
}
static void client(int fd){
    struct timeval timeout={2,0};setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    char request[4096];size_t used=0;
    while(used<sizeof(request)-1){ssize_t n=recv(fd,request+used,sizeof(request)-1-used,0);if(n<=0)return;used+=(size_t)n;request[used]=0;if(strstr(request,"\r\n\r\n"))break;}
    char method[16],path[1024],version[16];if(sscanf(request,"%15s %1023s %15s",method,path,version)!=3||strncmp(version,"HTTP/1.",7)){response(fd,400,"text/plain","Invalid request",15);return;}
    if(strcmp(method,"GET")){response(fd,405,"text/plain","GET only",8);return;}
    if(!strcmp(path,"/api/traces")){response(fd,200,"application/json","[]",2);return;}
    if(!strcmp(path,"/api/live")){
        pthread_mutex_lock(&mutex);waiting=0;pthread_mutex_unlock(&mutex);
        Buffer b=snapshot();if(b.bad)response(fd,503,"text/plain","Snapshot unavailable",20);else response(fd,200,"application/json",b.data,b.len);free(b.data);return;
    }
    const char *name=NULL,*type="text/plain";
    if(!strcmp(path,"/")||!strcmp(path,"/index.html")){name="index.html";type="text/html; charset=utf-8";}
    const char *js[]={"app.js","cpu.js","model.js","service-model.js"};
    for(size_t i=0;i<sizeof(js)/sizeof(*js);i++)if(path[0]=='/'&&!strcmp(path+1,js[i])){name=js[i];type="text/javascript; charset=utf-8";}
    if(!strcmp(path,"/style.css")){name="style.css";type="text/css; charset=utf-8";}
    if(!name){response(fd,404,"text/plain","Not found",9);return;}
    char filename[4096];if(snprintf(filename,sizeof(filename),"%s/%s",ui_dir,name)>=(int)sizeof(filename)){response(fd,500,"text/plain","Path too long",13);return;}
    FILE *file=fopen(filename,"rb");if(!file){response(fd,404,"text/plain","Missing UI file",15);return;}
    struct stat info;if(fstat(fileno(file),&info)||!S_ISREG(info.st_mode)||info.st_size>2*1024*1024){fclose(file);response(fd,500,"text/plain","Invalid UI file",15);return;}
    char *data=malloc((size_t)info.st_size+1);if(!data){fclose(file);return;}
    size_t size=fread(data,1,(size_t)info.st_size,file);fclose(file);response(fd,200,type,data,size);free(data);
}
static int number(const char *s,unsigned max,unsigned *value){char *end;errno=0;unsigned long n=strtoul(s,&end,10);if(errno||!*s||*end||n>max)return -1;*value=(unsigned)n;return 0;}
int main(int argc,char **argv){
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--")){program=argv+i+1;break;}
        if(!strcmp(argv[i],"--wait-client")){waiting=1;continue;}
        if(i+1>=argc){fprintf(stderr,"Missing option value\n");return 2;}
        const char *key=argv[i],*value=argv[++i];
        if(!strcmp(key,"--port")){if(number(value,65535,&port))return 2;}
        else if(!strcmp(key,"--listen"))listen_ip=value;
        else if(!strcmp(key,"--ui"))ui_dir=value;
        else if(!strcmp(key,"--capture-dir"))capture_dir=value;
        else if(!strcmp(key,"--helper"))helper=value;
        else if(!strcmp(key,"--fixture"))fixture=value;
        else if(!strcmp(key,"--replay-kev"))replay_kev=value;
        else if(!strcmp(key,"--seconds")){unsigned n;if(number(value,86400,&n))return 2;seconds=value;}
        else{fprintf(stderr,"Unknown option: %s\n",key);return 2;}
    }
    if(!fixture&&!replay_kev&&(!program||!program[0])){fprintf(stderr,"Usage: %s [--listen IPv4] [--port 8765] [--ui ui] [--capture-dir traces] [--helper ./watcher-qnx-capture] [--seconds 0] [--wait-client] -- <app> [args...]\n",argv[0]);return 2;}
#ifndef __QNXNTO__
    if(!fixture){fprintf(stderr,"Kernel collection requires QNX; --fixture is for tests only\n");return 2;}
#else
    frequency=SYSPAGE_ENTRY(qtime)->cycles_per_sec;if(!frequency){fprintf(stderr,"No cycle frequency\n");return 1;}
#endif
    struct stat directory;
    if(stat(capture_dir,&directory)||!S_ISDIR(directory.st_mode)){
        if(mkdir(capture_dir,0700)){perror("capture directory (use an existing writable directory)");return 1;}
    }
    if(snprintf(prefix,sizeof(prefix),"%s/service-%ld-%ld",capture_dir,(long)time(NULL),(long)getpid())>=(int)sizeof(prefix)||snprintf(kev,sizeof(kev),"%s.kev",prefix)>=(int)sizeof(kev))return 2;
    snprintf(session_name,sizeof(session_name),"service-%ld-%ld.events.log",(long)time(NULL),(long)getpid());
    if(replay_kev){if(strlen(replay_kev)>=sizeof(kev))return 2;strcpy(kev,replay_kev);}
    if(!fixture&&!replay_kev){setenv("WATCHER_QNX_BACKEND","kernel",1);setenv("WATCHER_LIVE_FLUSH","1",1);unsetenv("LTI_EVENT_FILE");}
    signal(SIGHUP,SIG_IGN);
    signal(SIGINT,on_signal);signal(SIGTERM,on_signal);signal(SIGPIPE,SIG_IGN);
    int server=socket(AF_INET,SOCK_STREAM,0);if(server<0){perror("socket");return 1;}
    fcntl(server,F_SETFD,FD_CLOEXEC);int yes=1;setsockopt(server,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
    struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons((uint16_t)port);
    if(inet_pton(AF_INET,listen_ip,&address.sin_addr)!=1){fprintf(stderr,"Invalid IPv4 address\n");close(server);return 2;}
    if(bind(server,(struct sockaddr*)&address,sizeof(address))||listen(server,8)){perror("HTTP listen");close(server);return 1;}
    socklen_t address_len=sizeof(address);getsockname(server,(struct sockaddr*)&address,&address_len);
    printf("Watcher service http://%s:%u (open the target IP from your browser)\nCapture prefix: %s\n",listen_ip,ntohs(address.sin_port),prefix);fflush(stdout);
    pthread_t collector_thread,reader_thread;
    pthread_attr_t attributes;pthread_attr_init(&attributes);
    if(pthread_attr_setstacksize(&attributes,512*1024)){pthread_attr_destroy(&attributes);close(server);return 1;}
    if(pthread_create(&collector_thread,&attributes,collector,NULL)){pthread_attr_destroy(&attributes);close(server);return 1;}
    if(pthread_create(&reader_thread,&attributes,reader,NULL)){pthread_attr_destroy(&attributes);stopping=1;pthread_join(collector_thread,NULL);close(server);return 1;}
    pthread_attr_destroy(&attributes);
    while(!stopping){
        fd_set readfds;FD_ZERO(&readfds);FD_SET(server,&readfds);struct timeval timeout={0,200000};
        int ready=select(server+1,&readfds,NULL,NULL,&timeout);if(ready<0&&errno!=EINTR){perror("select");break;}
        if(ready>0){int fd=accept(server,NULL,NULL);if(fd>=0){fcntl(fd,F_SETFD,FD_CLOEXEC);client(fd);close(fd);}}
    }
    stopping=1;pthread_mutex_lock(&mutex);finished=fixture?1:finished;pthread_mutex_unlock(&mutex);
    pthread_join(collector_thread,NULL);pthread_join(reader_thread,NULL);close(server);return failed?1:0;
}
