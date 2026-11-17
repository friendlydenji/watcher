CC ?= cc
AR ?= ar
CFLAGS ?= -O2
LTI_CFLAGS = -std=c11 -Wall -Wextra -Wpedantic -pthread

all: liblti.a

src/lti.o: src/lti.c include/lti/lti.h
	$(CC) $(CPPFLAGS) -Iinclude $(CFLAGS) $(LTI_CFLAGS) -c src/lti.c -o $@

liblti.a: src/lti.o
	$(AR) rcs $@ $^

clean:
	rm -f src/lti.o liblti.a

.PHONY: all clean
