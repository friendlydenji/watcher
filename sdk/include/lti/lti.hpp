#ifndef LTI_LTI_HPP
#define LTI_LTI_HPP

#include "lti.h"

#include <cstdint>

namespace lti {

class Session {
public:
    Session() : available_(lti_init() == 0) {}
    ~Session() { lti_shutdown(); }
    Session(const Session &) = delete;
    Session &operator=(const Session &) = delete;
    bool available() const { return available_; }

private:
    bool available_;
};

class Flow {
public:
    explicit Flow(std::uint64_t job_id) : job_id_(job_id) {}
    void send() const { lti_event(LTI_SEND, job_id_, 0); }
    void receive() const { lti_event(LTI_RECEIVE, job_id_, 0); }
    void done() const { lti_event(LTI_DONE, job_id_, 0); }
    void compute_begin() const { lti_event(LTI_COMPUTE_BEGIN, job_id_, 0); }
    void compute_end() const { lti_event(LTI_COMPUTE_END, job_id_, 0); }
    void sleep_begin() const { lti_event(LTI_SLEEP_BEGIN, job_id_, 0); }
    void sleep_end() const { lti_event(LTI_SLEEP_END, job_id_, 0); }

private:
    std::uint64_t job_id_;
};

} // namespace lti

#endif
