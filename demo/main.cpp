#if defined(__QNXNTO__)
#define _QNX_SOURCE
#endif
#include "worker.h"
#include "lti/lti.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <unistd.h>

int main(int argc, char **argv)
{
    int duration = 5;
    if (argc > 1) {
        char *end = nullptr;
        long value = std::strtol(argv[1], &end, 10);
        if (*end != '\0' || value < 1 || value > 60) {
            std::fprintf(stderr, "usage: %s [duration_seconds: 1..60]\n", argv[0]);
            return 2;
        }
        duration = static_cast<int>(value);
    }

    std::printf("main PID=%ld TID=%ld duration=%ds\n",
                static_cast<long>(getpid()), (long)lti_thread_id(), duration);
    std::fflush(stdout);
    lti::Session tracing;
    if (!tracing.available())
        std::fprintf(stderr, "LTI tracing unavailable; scheduler demo still runs\n");
    worker_t *worker = worker_start();
    if (!worker) {
        std::perror("worker_start");
        return 1;
    }

    auto end = std::chrono::steady_clock::now() + std::chrono::seconds(duration);
    unsigned job_id = 0;
    while (std::chrono::steady_clock::now() < end) {
        if (worker_submit(worker, ++job_id) != 0) {
            std::fprintf(stderr, "worker_submit failed\n");
            worker_stop(worker);
            return 1;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    worker_stop(worker);
    std::printf("main submitted=%u\n", job_id);
    return 0;
}
