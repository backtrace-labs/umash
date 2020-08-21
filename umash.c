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

#define ARRAY_SIZE(ARR) (sizeof(ARR) / sizeof(ARR[0]))

#define BLOCK_SIZE (sizeof(uint64_t) * UMASH_PH_PARAM_COUNT)

/* Incremental UMASH consumes 16 bytes at a time. */
#define INCREMENTAL_GRANULARITY 16

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

TEST_DEF uint64_t
umash_long(const uint64_t multipliers[static 2], const uint64_t *ph,
    uint64_t seed, const void *data, size_t n_bytes)
{
	uint64_t acc = 0;

	while (n_bytes > BLOCK_SIZE) {
		struct umash_ph compressed;

		compressed = ph_one_block(ph, seed, data);
		data = (const char *)data + BLOCK_SIZE;
		n_bytes -= BLOCK_SIZE;

		acc = horner_double_update(acc, multipliers[0], multipliers[1],
		    compressed.bits[0], compressed.bits[1]);
	}

	/* Do the final block. */
	{
		struct umash_ph compressed;

		seed ^= (uint8_t)n_bytes;
		compressed = ph_last_block(ph, seed, data, n_bytes);
		acc = horner_double_update(acc, multipliers[0], multipliers[1],
		    compressed.bits[0], compressed.bits[1]);
	}

	return finalize(acc);
}

static bool
value_is_repeated(const uint64_t *values, size_t n, uint64_t needle)
{

	for (size_t i = 0; i < n; i++) {
		if (values[i] == needle)
			return true;
	}

	return false;
}

bool
umash_params_prepare(struct umash_params *params)
{
	static const uint64_t modulo = (1UL << 61) - 1;
	/*
	 * The polynomial parameters have two redundant fields (for
	 * the pre-squared multipliers).  Use them as our source of
	 * extra entropy if needed.
	 */
	uint64_t buf[] = { params->poly[0][0], params->poly[1][0] };
	size_t buf_idx = 0;

#define GET_RANDOM(DST)                         \
	do {                                    \
		if (buf_idx >= ARRAY_SIZE(buf)) \
			return false;           \
                                                \
		(DST) = buf[buf_idx++];         \
	} while (0)

	/* Check the polynomial multipliers: we don't want 0s. */
	for (size_t i = 0; i < ARRAY_SIZE(params->poly); i++) {
		uint64_t f = params->poly[i][1];

		while (true) {
			/*
			 * Zero out bits and use rejection sampling to
			 * guarantee uniformity.
			 */
			f &= (1UL << 61) - 1;
			if (f != 0 && f < modulo)
				break;

			GET_RANDOM(f);
		}

		/* We can work in 2**64 - 8 and reduce after the fact. */
		params->poly[i][0] = mul_mod_fast(f, f) % modulo;
		params->poly[i][1] = f;
	}

	/* Avoid repeated PH noise values. */
	for (size_t i = 0; i < ARRAY_SIZE(params->ph); i++) {
		while (value_is_repeated(params->ph, i, params->ph[i]))
			GET_RANDOM(params->ph[i]);
	}

	return true;
}

/*
 * Updates the polynomial state at the end of a block.
 */
static void
sink_update_poly(struct umash_sink *sink)
{
	const __m128i ph_acc = _mm_cvtsi64_si128(sink->seed);
	/*
	 * Size of the current block in bytes, modulo 256.  May only
	 * be non-zero for the last block.
	 */
	uint8_t block_size = sink->block_size;

	for (size_t i = 0; i < (sink->fingerprinting ? 2 : 1); i++) {
		uint64_t ph0 = sink->ph_acc[i].bits[0] ^ block_size;
		uint64_t ph1 = sink->ph_acc[i].bits[1];

		sink->poly_state[i].acc = horner_double_update(
		    sink->poly_state[i].acc, sink->poly_state[i].mul[0],
		    sink->poly_state[i].mul[1], ph0, ph1);

		memcpy(&sink->ph_acc[i], &ph_acc, sizeof(ph_acc));
	}

	return;
}

/* Updates the PH state with 16 bytes of data. */
static void
sink_consume_buf(
    struct umash_sink *sink, const char buf[static INCREMENTAL_GRANULARITY])
{
	const size_t buf_begin = sizeof(sink->buf) - INCREMENTAL_GRANULARITY;

	for (size_t i = 0, param = sink->ph_iter;
	     i < (sink->fingerprinting ? 2 : 1);
	     i++, param += UMASH_PH_TOEPLITZ_SHIFT) {
		__m128i acc;
		uint64_t x, y;

		memcpy(&x, buf, sizeof(x));
		memcpy(&y, buf + sizeof(x), sizeof(y));

		/* Use GPR loads to avoid forwarding stalls.  */
		x ^= sink->ph[param];
		y ^= sink->ph[param + 1];
		memcpy(&acc, &sink->ph_acc[i], sizeof(acc));
		acc ^= _mm_clmulepi64_si128(
		    _mm_cvtsi64_si128(x), _mm_cvtsi64_si128(y), 0);
		memcpy(&sink->ph_acc[i], &acc, sizeof(acc));
	}

	memmove(&sink->buf, buf, buf_begin);
	sink->block_size += sink->bufsz;
	sink->bufsz = 0;
	sink->ph_iter += 2;
	sink->large_umash = true;

	if (sink->ph_iter == UMASH_PH_PARAM_COUNT) {
		sink_update_poly(sink);
		sink->block_size = 0;
		sink->ph_iter = 0;
	}

	return;
}

void
umash_sink_update(struct umash_sink *sink, const void *data, size_t n_bytes)
{
	const size_t buf_begin = sizeof(sink->buf) - INCREMENTAL_GRANULARITY;
	size_t remaining = INCREMENTAL_GRANULARITY - sink->bufsz;

	if (n_bytes < remaining) {
		memcpy(&sink->buf[buf_begin + sink->bufsz], data, n_bytes);
		sink->bufsz += n_bytes;
		return;
	}

	memcpy(&sink->buf[buf_begin + sink->bufsz], data, remaining);
	data = (const char *)data + remaining;
	n_bytes -= remaining;
	sink->bufsz = INCREMENTAL_GRANULARITY;
	sink_consume_buf(sink, sink->buf + buf_begin);

	while (n_bytes >= INCREMENTAL_GRANULARITY) {
		n_bytes -= INCREMENTAL_GRANULARITY;

		sink->bufsz = INCREMENTAL_GRANULARITY;
		/* Copy if this is the last full chunk. */
		sink_consume_buf(sink, data);
		data = (const char *)data + INCREMENTAL_GRANULARITY;
	}

	memcpy(&sink->buf[buf_begin], data, n_bytes);
	sink->bufsz = n_bytes;
	return;
}

uint64_t
umash_full(const struct umash_params *params, uint64_t seed, int which,
    const void *data, size_t n_bytes)
{
	const size_t shift = (which == 0) ? 0 : UMASH_PH_TOEPLITZ_SHIFT;

	which = (which == 0) ? 0 : 1;
	/*
	 * It's not that short inputs are necessarily more likely, but
	 * we want to make sure they fall through correctly to
	 * minimise latency.
	 */
	if (LIKELY(n_bytes <= sizeof(__m128i))) {
		if (LIKELY(n_bytes <= sizeof(uint64_t)))
			return umash_short(
			    &params->ph[shift], seed, data, n_bytes);

		return umash_medium(params->poly[which], &params->ph[shift],
		    seed, data, n_bytes);
	}

	return umash_long(
	    params->poly[which], &params->ph[shift], seed, data, n_bytes);
}

struct umash_fp
umash_fprint(const struct umash_params *params, uint64_t seed, const void *data,
    size_t n_bytes)
{
	struct umash_fp ret;
	const size_t toeplitz_shift = UMASH_PH_TOEPLITZ_SHIFT;

	if (n_bytes <= sizeof(__m128i)) {
		if (n_bytes <= sizeof(uint64_t)) {
			for (size_t i = 0, shift = 0; i < 2;
			     i++, shift = toeplitz_shift) {
				ret.hash[i] = umash_short(
				    &params->ph[shift], seed, data, n_bytes);
			}

			return ret;
		}

		for (size_t i = 0, shift = 0; i < 2;
		     i++, shift = toeplitz_shift) {
			ret.hash[i] = umash_medium(params->poly[i],
			    &params->ph[shift], seed, data, n_bytes);
		}

		return ret;
	}

	for (size_t i = 0, shift = 0; i < 2; i++, shift = toeplitz_shift) {
		ret.hash[i] = umash_long(
		    params->poly[i], &params->ph[shift], seed, data, n_bytes);
	}

	return ret;
}

void
umash_init(struct umash_state *state, const struct umash_params *params,
    uint64_t seed, int which)
{
	const size_t shift = (which == 0) ? 0 : UMASH_PH_TOEPLITZ_SHIFT;

	which = (which == 0) ? 0 : 1;
	state->sink = (struct umash_sink) {
		.poly_state[0] = {
			.mul = {
				params->poly[which][0],
				params->poly[which][1],
			},
		},
		.ph = &params->ph[shift],
		.ph_acc[0].bits[0] = seed,
		.seed = seed,
	};

	return;
}

void
umash_fp_init(struct umash_fp_state *state, const struct umash_params *params,
    uint64_t seed)
{

	state->sink = (struct umash_sink) {
		.poly_state[0] = {
			.mul = {
				params->poly[0][0],
				params->poly[0][1],
			},
		},
		.poly_state[1]= {
			.mul = {
				params->poly[1][0],
				params->poly[1][1],
			},
		},
		.ph = params->ph,
		.fingerprinting = true,
		.ph_acc[0].bits[0] = seed,
		.ph_acc[1].bits[0] = seed,
		.seed = seed,
	};

	return;
}

/**
 * Pumps any last block out of the incremental state.
 */
static void
digest_flush(struct umash_sink *sink)
{

	if (sink->bufsz > 0)
		sink_consume_buf(sink, &sink->buf[sink->bufsz]);

	if (sink->block_size != 0)
		sink_update_poly(sink);
	return;
}

/**
 * Finalizes a digest out of `sink`'s current state.
 *
 * The `sink` must be `digest_flush`ed if it is a `large_umash`.
 *
 * @param index 0 to return the first (only, if hashing) value, 1 for the
 *   second independent value for fingerprinting.
 */
static uint64_t
digest(const struct umash_sink *sink, int index)
{
	const size_t buf_begin = sizeof(sink->buf) - INCREMENTAL_GRANULARITY;
	const size_t shift = index * UMASH_PH_TOEPLITZ_SHIFT;

	if (sink->large_umash)
		return finalize(sink->poly_state[index].acc);

	if (sink->bufsz <= sizeof(uint64_t))
		return umash_short(&sink->ph[shift], sink->seed,
		    &sink->buf[buf_begin], sink->bufsz);

	return umash_medium(sink->poly_state[index].mul, &sink->ph[shift],
	    sink->seed, &sink->buf[buf_begin], sink->bufsz);
}

uint64_t
umash_digest(const struct umash_state *state)
{
	struct umash_sink copy;
	const struct umash_sink *sink = &state->sink;

	if (sink->large_umash) {
		copy = *sink;
		digest_flush(&copy);
		sink = &copy;
	}

	return digest(sink, 0);
}

struct umash_fp
umash_fp_digest(const struct umash_fp_state *state)
{
	struct umash_sink copy;
	struct umash_fp ret;
	const struct umash_sink *sink = &state->sink;

	if (sink->large_umash) {
		copy = *sink;
		digest_flush(&copy);
		sink = &copy;
	}

	for (size_t i = 0; i < ARRAY_SIZE(ret.hash); i++)
		ret.hash[i] = digest(sink, i);

	return ret;
}
