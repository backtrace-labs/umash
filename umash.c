#include "umash.h"

/* The PH block reduction code is x86-only for now. */
#include <immintrin.h>
#include <string.h>

/*
 * UMASH is distributed under the MIT license.
 *
 * SPDX-License-Identifier: MIT
 * Copyright 2020 Backtrace I/O, Inc.
 *
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use, copy,
 * modify, merge, publish, distribute, sublicense, and/or sell copies
 * of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
 * BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
 * ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
 * CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

#ifdef UMASH_TEST_ONLY
#define TEST_DEF
#include "t/umash_test_only.h"
#else
#define TEST_DEF static
#endif

#ifdef __GNUC__
#define LIKELY(X) __builtin_expect(!!(X), 1)
#define UNLIKELY(X) __builtin_expect(!!(X), 0)
#else
#define LIKELY(X) X
#define UNLIKELY(X) X
#endif

/**
 * Modular arithmetic utilities.
 *
 * The code below uses GCC internals.  It should be possible to add
 * support for other compilers.
 */
TEST_DEF inline uint64_t
add_mod_fast(uint64_t x, uint64_t y)
{
	unsigned long long sum;

	/* If `sum` overflows, `sum + 8` does not. */
	return (__builtin_uaddll_overflow(x, y, &sum) ? sum + 8 : sum);
}

static uint64_t
add_mod_slow_slow_path(uint64_t sum, uint64_t fixup)
{
	/* Reduce sum, mod 2**64 - 8. */
	sum = (sum >= (uint64_t)-8) ? sum + 8 : sum;
	/* sum < 2**64 - 8, so this doesn't overflow. */
	sum += fixup;
	/* Reduce again. */
	sum = (sum >= (uint64_t)-8) ? sum + 8 : sum;
	return sum;
}

TEST_DEF inline uint64_t
add_mod_slow(uint64_t x, uint64_t y)
{
	unsigned long long sum;
	uint64_t fixup = 0;

	/* x + y \equiv sum + fixup */
	if (__builtin_uaddll_overflow(x, y, &sum))
		fixup = 8;

	/*
	 * We must ensure `sum + fixup < 2**64 - 8`.
	 *
	 * We want a conditional branch here, but not in the
	 * overflowing add: overflows happen roughly half the time on
	 * pseudorandom inputs, but `sum < 2**64 - 16` is almost
	 * always true, for pseudorandom `sum`.
	 */
	if (LIKELY(sum < (uint64_t)-16))
		return sum + fixup;

	return add_mod_slow_slow_path(sum, fixup);
}

TEST_DEF inline uint64_t
mul_mod_fast(uint64_t m, uint64_t x)
{
	__uint128_t product = m;

	product *= x;
	return add_mod_fast((uint64_t)product, 8 * (uint64_t)(product >> 64));
}

TEST_DEF inline uint64_t
horner_double_update(
    uint64_t acc, uint64_t m0, uint64_t m1, uint64_t x, uint64_t y)
{

	acc = add_mod_fast(acc, x);
	return add_mod_slow(mul_mod_fast(m0, acc), mul_mod_fast(m1, y));
}

/**
 * PH block compression.
 */
TEST_DEF struct umash_ph
ph_one_block(const uint64_t *params, uint64_t seed, const void *block)
{
	struct umash_ph ret;
	__m128i acc = _mm_cvtsi64_si128(seed);

	for (size_t i = 0; i < UMASH_PH_PARAM_COUNT; i += 2) {
		__m128i x, k;

		memcpy(&x, block, sizeof(x));
		block = (const char *)block + sizeof(x);

		memcpy(&k, &params[i], sizeof(k));
		x ^= k;
		acc ^= _mm_clmulepi64_si128(x, x, 1);
	}

	memcpy(&ret, &acc, sizeof(ret));
	return ret;
}

TEST_DEF struct umash_ph
ph_last_block(
    const uint64_t *params, uint64_t seed, const void *block, size_t n_bytes)
{
	struct umash_ph ret;
	__m128i acc = _mm_cvtsi64_si128(seed);

	/* The final block processes `remaining > 0` bytes. */
	size_t remaining = 1 + ((n_bytes - 1) % sizeof(__m128i));
	size_t end_full_pairs = (n_bytes - remaining) / sizeof(uint64_t);
	const void *last_ptr = (const char *)block + n_bytes - sizeof(__m128i);
	size_t i;

	for (i = 0; i < end_full_pairs; i += 2) {
		__m128i x, k;

		memcpy(&x, block, sizeof(x));
		block = (const char *)block + sizeof(x);

		memcpy(&k, &params[i], sizeof(k));
		x ^= k;
		acc ^= _mm_clmulepi64_si128(x, x, 1);
	}

	/* Compress the final (potentially partial) pair. */
	{
		uint64_t x, y;

		memcpy(&x, last_ptr, sizeof(x));
		last_ptr = (const char *)last_ptr + sizeof(x);
		memcpy(&y, last_ptr, sizeof(y));

		x ^= params[i];
		y ^= params[i + 1];

		acc ^= _mm_clmulepi64_si128(
		    _mm_cvtsi64_si128(x), _mm_cvtsi64_si128(y), 0);
	}

	memcpy(&ret, &acc, sizeof(ret));
	return ret;
}

/**
 * Short UMASH (<= 8 bytes).
 */
TEST_DEF inline uint64_t
vec_to_u64(const void *data, size_t n_bytes)
{
	const char zeros[2] = { 0 };
	uint32_t hi, lo;

	/*
	 * If there are at least 4 bytes to read, read the first 4 in
	 * `lo`, and the last 4 in `hi`.  This covers the whole range,
	 * since `n_bytes` is at most 8.
	 */
	if (LIKELY(n_bytes >= sizeof(lo))) {
		memcpy(&lo, data, sizeof(lo));
		memcpy(
		    &hi, (const char *)data + n_bytes - sizeof(hi), sizeof(hi));
	} else {
		/* 0 <= n_bytes < 4.  Decode the size in binary. */
		uint16_t word;
		uint8_t byte;

		/*
		 * If the size is odd, load the first byte in `byte`;
		 * otherwise, load in a zero.
		 */
		memcpy(&byte, ((n_bytes & 1) != 0) ? data : zeros, 1);
		lo = byte;

		/*
		 * If the size is 2 or 3, load the last two bytes in `word`;
		 * otherwise, load in a zero.
		 */
		memcpy(&word,
		    ((n_bytes & 2) != 0) ? (const char *)data + n_bytes - 2 :
					   zeros,
		    2);
		/*
		 * We have now read `bytes[0 ... n_bytes - 1]`
		 * exactly once without overwriting any data.
		 */
		hi = word;
	}

	/*
	 * Mix `hi` with the `lo` bits: SplitMix64 seems to have
	 * trouble with the top 4 bits.
	 */
	return ((uint64_t)hi << 32) | (lo + hi);
}

TEST_DEF uint64_t
umash_short(
    const uint64_t *params, uint64_t seed, const void *data, size_t n_bytes)
{
	uint64_t h;

	seed += params[n_bytes];
	h = vec_to_u64(data, n_bytes);
	h ^= h >> 30;
	h *= 0xbf58476d1ce4e5b9ULL;
	h = (h ^ seed) ^ (h >> 27);
	h *= 0x94d049bb133111ebULL;
	h ^= h >> 31;
	return h;
}

TEST_DEF inline uint64_t
finalize(uint64_t x)
{

	x ^= x >> 27;
	x *= 0x94d049bb133111ebUL;
	return x;
}

TEST_DEF uint64_t
umash_medium(const uint64_t multipliers[static 2], const uint64_t *ph,
    uint64_t seed, const void *data, size_t n_bytes)
{
	union {
		__m128i vec;
		uint64_t u64[2];
	} acc = { .vec = _mm_cvtsi64_si128(seed ^ n_bytes) };

	{
		uint64_t x, y;

		memcpy(&x, data, sizeof(x));
		memcpy(&y, (const char *)data + n_bytes - sizeof(y), sizeof(y));
		x ^= ph[0];
		y ^= ph[1];

		acc.vec ^= _mm_clmulepi64_si128(
		    _mm_cvtsi64_si128(x), _mm_cvtsi64_si128(y), 0);
	}

	return finalize(horner_double_update(
	    /*acc=*/0, multipliers[0], multipliers[1], acc.u64[0], acc.u64[1]));
}
