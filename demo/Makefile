CC ?= cc
CXX ?= c++
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c11
CXXFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c++17
CPPFLAGS += -I../sdk/include

all: mixed_demo

../sdk/liblti.a: ../sdk/src/lti.c ../sdk/include/lti/lti.h
	$(MAKE) -C ../sdk

worker.o: worker.c worker.h ../sdk/include/lti/lti.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -pthread -c worker.c -o $@

main.o: main.cpp worker.h ../sdk/include/lti/lti.hpp
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -pthread -c main.cpp -o $@

mixed_demo: main.o worker.o ../sdk/liblti.a
	$(CXX) -pthread main.o worker.o ../sdk/liblti.a -o $@

clean:
	rm -f main.o worker.o mixed_demo

.PHONY: all clean
