#pragma once

#include <stdint.h>

/**
 * xoshiro256+, wrapped with a re-entrant interface.
 *
 * Written in 2018 by David Blackman and Sebastiano Vigna (vigna@acm.org)
 *
 * Released under CC0 (http://creativecommons.org/publicdomain/zero/1.0/).
 */

struct xoshiro {
	uint64_t s[4];
};

static inline uint64_t
xoshiro_next(struct xoshiro *state)
{
	uint64_t *s = state->s;
	const uint64_t result = s[0] + s[3];
	const uint64_t t = s[1] << 17;

	s[2] ^= s[0];
	s[3] ^= s[1];
	s[1] ^= s[2];
	s[0] ^= s[3];

	s[2] ^= t;

	s[3] = (s[3] << 45) | (s[2] >> (64 - 45));
	return result;
}

/**
 * Seeds the global xoshiro PRNG state.
 */
void xoshiro_seed_global_state(uint64_t seed);

/**
 * Extracts a fresh state from the global PRNG state.
 */
struct xoshiro xoshiro_get(void);

/**
 * Returns a snapshot of the input state, before advancing it by 2^128
 * calls.
 */
struct xoshiro xoshiro_jump(struct xoshiro *);

/**
 * Returns a snapshot of the input state, before advancing it by 2^192
 * calls.
 */
struct xoshiro xoshiro_long_jump(struct xoshiro *);
