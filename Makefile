all: examples/job_only/job_only
	$(MAKE) -C sdk
	$(MAKE) -C demo
	$(MAKE) -C examples/c_demo

tests/test_sdk: tests/test_sdk.c sdk/src/lti.c sdk/include/lti/lti.h
	$(CC) $(CPPFLAGS) -Isdk/include $(CFLAGS) -std=c11 -Wall -Wextra -Wpedantic -pthread tests/test_sdk.c sdk/src/lti.c -Wl,--wrap=pthread_mutex_unlock -o $@

tests/benchmark_sdk: tests/benchmark_sdk.c sdk/src/lti.c sdk/include/lti/lti.h
	$(CC) $(CPPFLAGS) -Isdk/include $(CFLAGS) -O2 -std=c11 -Wall -Wextra -Wpedantic -pthread tests/benchmark_sdk.c sdk/src/lti.c -o $@

benchmark: tests/benchmark_sdk
	./tests/benchmark_sdk

examples/job_only/job_only: examples/job_only/main.c sdk/src/lti.c sdk/include/lti/lti.h
	$(CC) $(CPPFLAGS) -Isdk/include $(CFLAGS) -O2 -std=c11 -Wall -Wextra -Wpedantic -pthread examples/job_only/main.c sdk/src/lti.c -o $@

tests/test_portable: tests/test_portable.c sdk/src/lti.c sdk/include/lti/lti.h
	$(CC) $(CPPFLAGS) -Isdk/include $(CFLAGS) -O2 -std=c11 -Wall -Wextra -Wpedantic -pthread tests/test_portable.c sdk/src/lti.c -o $@

test: tests/test_sdk tests/test_portable
	./tests/test_portable
	./tests/test_sdk
	python3 -m unittest discover -s tests -v
	node tests/test_ui.js

clean:
	$(MAKE) -C demo clean
	$(MAKE) -C examples/c_demo clean
	$(MAKE) -C sdk clean
	rm -f tests/test_sdk tests/test_portable tests/benchmark_sdk examples/job_only/job_only

.PHONY: all test clean benchmark
