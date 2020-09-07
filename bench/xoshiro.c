#include "xoshiro.h"

#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

static struct {
	struct xoshiro state;
	pthread_mutex_t lock;
} xoshiro_global_state = {
        .state.s = {
                /* Provided by random.org */
                0x0e69f85f1e6e2da2ULL,
                0x834b452a6e0fa76bULL,
                0x91c03d676d758518ULL,
                0x7d50bf482d57a7a2ULL,
        },
        .lock = PTHREAD_MUTEX_INITIALIZER,
};

/**
 * Blackman and Vigna suggest the use a splitmix generator to expand a
 * 64-bit seed into a 256-bit xoshiro state: we want a different
 * structure in the expander and in the generator.
 *
 * splitmix64 was written in 2015 by Sebastiano Vigna (vigna@acm.org)
 * and released under CC0 (http://creativecommons.org/publicdomain/zero/1.0/)
 */
static uint64_t
splitmix64_next(uint64_t *x)
{
	uint64_t z = (*x += 0x9e3779b97f4a7c15);

	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9;
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb;
	return z ^ (z >> 31);
}

static bool
state_all_zero(const struct xoshiro *state)
{
	const struct xoshiro all_zero = { 0 };

	return memcmp(state, &all_zero, sizeof(all_zero)) == 0;
}

void
xoshiro_seed_global_state(uint64_t seed)
{
	const size_t state_size = sizeof(xoshiro_global_state.state.s) /
	    sizeof(xoshiro_global_state.state.s[0]);

	pthread_mutex_lock(&xoshiro_global_state.lock);

	do {
		for (size_t i = 0; i < state_size; i++)
			xoshiro_global_state.state.s[i] = splitmix64_next(&seed);
	} while (state_all_zero(&xoshiro_global_state.state));

	pthread_mutex_unlock(&xoshiro_global_state.lock);
	return;
}

struct xoshiro
xoshiro_get(void)
{
	struct xoshiro ret;

	pthread_mutex_lock(&xoshiro_global_state.lock);
	ret = xoshiro_long_jump(&xoshiro_global_state.state);
	pthread_mutex_unlock(&xoshiro_global_state.lock);

	return ret;
}

struct xoshiro
xoshiro_jump(struct xoshiro *cursor)
{
	static const uint64_t JUMP[] = { 0x180ec6d33cfd0aba, 0xd5a61266f0c9392c,
		0xa9582618e03fc9aa, 0x39abdc4529b1661c };
	const struct xoshiro ret = *cursor;
	uint64_t *s = cursor->s;
	uint64_t s0 = 0;
	uint64_t s1 = 0;
	uint64_t s2 = 0;
	uint64_t s3 = 0;
	for (size_t i = 0; i < sizeof JUMP / sizeof *JUMP; i++)
		for (size_t b = 0; b < 64; b++) {
			if (JUMP[i] & UINT64_C(1) << b) {
				s0 ^= s[0];
				s1 ^= s[1];
				s2 ^= s[2];
				s3 ^= s[3];
			}
			xoshiro_next(cursor);
		}

	s[0] = s0;
	s[1] = s1;
	s[2] = s2;
	s[3] = s3;

	return ret;
}

struct xoshiro
xoshiro_long_jump(struct xoshiro *cursor)
{
	static const uint64_t LONG_JUMP[] = { 0x76e15d3efefdcbbf, 0xc5004e441c522fb3,
		0x77710069854ee241, 0x39109bb02acbe635 };
	const struct xoshiro ret = *cursor;
	uint64_t *s = cursor->s;
	uint64_t s0 = 0;
	uint64_t s1 = 0;
	uint64_t s2 = 0;
	uint64_t s3 = 0;
	for (size_t i = 0; i < sizeof LONG_JUMP / sizeof *LONG_JUMP; i++)
		for (size_t b = 0; b < 64; b++) {
			if (LONG_JUMP[i] & UINT64_C(1) << b) {
				s0 ^= s[0];
				s1 ^= s[1];
				s2 ^= s[2];
				s3 ^= s[3];
			}
			xoshiro_next(cursor);
		}

	s[0] = s0;
	s[1] = s1;
	s[2] = s2;
	s[3] = s3;
	return ret;
}
