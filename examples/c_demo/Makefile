CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -std=c11
CPPFLAGS += -I../../sdk/include

all: c_pingpong

../../sdk/liblti.a: ../../sdk/src/lti.c ../../sdk/include/lti/lti.h
	$(MAKE) -C ../../sdk

c_pingpong: main.c ../../sdk/liblti.a
	$(CC) $(CPPFLAGS) $(CFLAGS) -pthread main.c ../../sdk/liblti.a -o $@

clean:
	rm -f c_pingpong

.PHONY: all clean
