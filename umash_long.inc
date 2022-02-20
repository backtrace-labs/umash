/* -*- mode: c; -*- vim: set ft=c: */

/**
 * More wasteful routine for longer inputs (that can absorb I$ misses
 * and fixed setup work).
 */
#if UMASH_LONG_INPUTS
/*
 * Minimum byte size before switching to `umash_multiple_blocks`.
 *
 * Leaving this variable undefined disable calls to
 * `umash_multiple_blocks.
 */
#define UMASH_MULTIPLE_BLOCKS_THRESHOLD 1024
#endif

/**
 * Updates a 64-bit UMASH state for `n_blocks` 256-byte blocks in data.
 */
TEST_DEF HOT uint64_t
umash_multiple_blocks(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	uint64_t params[UMASH_OH_PARAM_COUNT] __attribute__((__aligned__(16)));
	const uint64_t m0 = multipliers[0];
	const uint64_t m1 = multipliers[1];
	uint64_t ret = initial;

	memcpy(params, oh_ptr, sizeof(params));

	for (size_t block_count = 0; block_count < n_blocks; block_count++) {
		const void *data = blocks;
		struct umash_oh oh;
		v128 acc = V128_ZERO;

		blocks = (const char *)blocks + BLOCK_SIZE;

#define PH(I)                                          \
	do {                                           \
		v128 x, k;                             \
                                                       \
		memcpy(&x, data, sizeof(x));           \
		data = (const char *)data + sizeof(x); \
                                                       \
		memcpy(&k, &params[I], sizeof(k));     \
		x ^= k;                                \
		acc ^= v128_clmul_cross(x);            \
	} while (0)

		PH(0);
		PH(2);
		PH(4);
		PH(6);
		PH(8);
		PH(10);
		PH(12);
		PH(14);
		PH(16);
		PH(18);
		PH(20);
		PH(22);
		PH(24);
		PH(26);
		PH(28);

#undef PH

		memcpy(&oh, &acc, sizeof(oh));

		/* Final ENH chunk. */
		{
			__uint128_t enh = (__uint128_t)seed << 64;
			uint64_t x, y;

			memcpy(&x, data, sizeof(x));
			data = (const char *)data + sizeof(x);
			memcpy(&y, data, sizeof(y));
			data = (const char *)data + sizeof(y);

			x += params[30];
			y += params[31];
			enh += (__uint128_t)x * y;

			oh.bits[0] ^= (uint64_t)enh;
			oh.bits[1] ^= (uint64_t)(enh >> 64) ^ (uint64_t)enh;
		}

		ret = horner_double_update(ret, m0, m1, oh.bits[0], oh.bits[1]);
	}

	return ret;
}
