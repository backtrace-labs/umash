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

typedef uint64_t umash_multiple_blocks_fn(uint64_t initial,
    const uint64_t multipliers[static 2], const uint64_t *oh_ptr, uint64_t seed,
    const void *blocks, size_t n_blocks);

/**
 * Updates a 64-bit UMASH state for `n_blocks` 256-byte blocks in data.
 */
TEST_DEF umash_multiple_blocks_fn umash_multiple_blocks_generic;

/**
 * Runtime dispatch logic.  When dynamic dispatch is enabled,
 * `umash_multiple_blocks` just forwards the call to
 * `umash_multiple_blocks_impl`, a function pointer.  That pointer is
 * initialised with a function that updates
 * `umash_multiple_blocks_impl` with an implementation appropriate for
 * the current CPU and tail-calls to that chosen implementation.
 *
 * When dynamic dispatch is disabled, `umash_multiple_blocks` just
 * always forwards to `umash_multiple_blocks_generic`.
 */
#if defined(__x86_64__) && UMASH_DYNAMIC_DISPATCH
#include <cpuid.h>

static umash_multiple_blocks_fn umash_multiple_blocks_pick,
    umash_multiple_blocks_vpclmulqdq;

static umash_multiple_blocks_fn *umash_multiple_blocks_impl = umash_multiple_blocks_pick;

static COLD FN uint64_t
umash_multiple_blocks_pick(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	bool has_vpclmulqdq = false;

	{
		const uint32_t extended_features_level = 7;
		const uint32_t vpclmulqdq_bit = 1UL << 10;
		uint32_t eax, ebx, ecx, edx;

		eax = ebx = ecx = edx = 0;
		__asm__("cpuid" : "+a"(eax), "+b"(ebx), "+c"(ecx), "+d"(edx));
		if (eax >= extended_features_level) {
			eax = extended_features_level;
			ebx = ecx = edx = 0;
			__asm__("cpuid" : "+a"(eax), "+b"(ebx), "+c"(ecx), "+d"(edx));
			has_vpclmulqdq = (ecx & vpclmulqdq_bit) != 0;
		}
	}

	if (has_vpclmulqdq) {
		umash_multiple_blocks_impl = umash_multiple_blocks_vpclmulqdq;
	} else {
		umash_multiple_blocks_impl = umash_multiple_blocks_generic;
	}

	return umash_multiple_blocks_impl(
	    initial, multipliers, oh_ptr, seed, blocks, n_blocks);
}

TEST_DEF inline uint64_t
umash_multiple_blocks(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	return umash_multiple_blocks_impl(
	    initial, multipliers, oh_ptr, seed, blocks, n_blocks);
}
#else
TEST_DEF inline uint64_t
umash_multiple_blocks(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	return umash_multiple_blocks_generic(
	    initial, multipliers, oh_ptr, seed, blocks, n_blocks);
}
#endif

TEST_DEF HOT uint64_t
umash_multiple_blocks_generic(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	const uint64_t m0 = multipliers[0];
	const uint64_t m1 = multipliers[1];
	const uint64_t kx = oh_ptr[UMASH_OH_PARAM_COUNT - 2];
	const uint64_t ky = oh_ptr[UMASH_OH_PARAM_COUNT - 1];
	uint64_t ret = initial;
	size_t block_count = 1;

	assert(n_blocks > 0);

	do {
		const void *data = blocks;
		struct umash_oh oh;
		v128 acc = V128_ZERO;

		blocks = (const char *)blocks + BLOCK_SIZE;

		/*
		 * FORCE() makes sure the compiler computes the value
		 * of `acc` at that program points.  Forcing a full
		 * computation prevents the compiler from evaluating
		 * the inner loop's xor-reduction tree widely: the
		 * bottleneck is in the carryless multiplications.
		 */
#define FORCE() __asm__("" : "+x"(acc))
#define PH(I)                                          \
	do {                                           \
		v128 x, k;                             \
                                                       \
		memcpy(&x, data, sizeof(x));           \
		data = (const char *)data + sizeof(x); \
                                                       \
		memcpy(&k, &oh_ptr[I], sizeof(k));     \
		x ^= k;                                \
		acc ^= v128_clmul_cross(x);            \
	} while (0)

		PH(0);
		PH(2);
		FORCE();

		PH(4);
		PH(6);
		FORCE();

		PH(8);
		PH(10);
		FORCE();

		PH(12);
		PH(14);
		FORCE();

		PH(16);
		PH(18);
		FORCE();

		PH(20);
		PH(22);
		FORCE();

		PH(24);
		PH(26);
		FORCE();

		PH(28);
#undef PH
#undef FORCE

		memcpy(&oh, &acc, sizeof(oh));

		/* Final ENH chunk. */
		{
			__uint128_t enh = (__uint128_t)seed << 64;
			uint64_t x, y;

			memcpy(&x, data, sizeof(x));
			data = (const char *)data + sizeof(x);
			memcpy(&y, data, sizeof(y));
			data = (const char *)data + sizeof(y);

			x += kx;
			y += ky;
			enh += (__uint128_t)x * y;

			oh.bits[0] ^= (uint64_t)enh;
			oh.bits[1] ^= (uint64_t)(enh >> 64) ^ (uint64_t)enh;
		}

		ret = horner_double_update(ret, m0, m1, oh.bits[0], oh.bits[1]);
	} while (block_count++ < n_blocks);

	return ret;
}

#if defined(__x86_64__) && UMASH_DYNAMIC_DISPATCH
/**
 * Updates a 64-bit UMASH state for `n_blocks` 256-byte blocks in data.
 */
TEST_DEF HOT __attribute__((__target__(("avx2,vpclmulqdq")))) uint64_t
umash_multiple_blocks_vpclmulqdq(uint64_t initial, const uint64_t multipliers[static 2],
    const uint64_t *oh_ptr, uint64_t seed, const void *blocks, size_t n_blocks)
{
	/*
	 * This type represents unaligned AVX2-sized regions of
	 * memory.
	 */
	struct b256 {
		char bytes[32];
	};

	const uint64_t m0 = multipliers[0];
	const uint64_t m1 = multipliers[1];
	__m256i k0, k4, k8, k12, k16, k20, k24;
	v128 k28;
	const uint64_t kx = oh_ptr[UMASH_OH_PARAM_COUNT - 2];
	const uint64_t ky = oh_ptr[UMASH_OH_PARAM_COUNT - 1];
	uint64_t ret = initial;

	assert(n_blocks > 0);

#define LOADU(DST, PTR) \
	__asm__("vmovdqu %1, %0" : "=x"(DST) : "m"(*(const struct b256 *)PTR))

	LOADU(k0, &oh_ptr[0]);
	LOADU(k4, &oh_ptr[4]);
	LOADU(k8, &oh_ptr[8]);
	LOADU(k12, &oh_ptr[12]);
	LOADU(k16, &oh_ptr[16]);
	LOADU(k20, &oh_ptr[20]);
	LOADU(k24, &oh_ptr[24]);
	memcpy(&k28, &oh_ptr[28], sizeof(k28));

	do {
		const void *data = blocks;
		struct umash_oh oh;
		__m256i acc2 = _mm256_setzero_si256();

		blocks = (const char *)blocks + BLOCK_SIZE;

#define PH(I)                                          \
	do {                                           \
		__m256i x;                             \
                                                       \
		LOADU(x, data);                        \
		data = (const char *)data + sizeof(x); \
                                                       \
		x = _mm256_xor_si256(x, k##I);         \
		x = _mm256_clmulepi64_epi128(x, x, 1); \
		acc2 = _mm256_xor_si256(acc2, x);      \
	} while (0)

		PH(0);
		PH(4);
		PH(8);
		PH(12);
		PH(16);
		PH(20);
		PH(24);

#undef PH
#undef LOADU

		{
			v128 x;

			memcpy(&x, data, sizeof(x));
			data = (const char *)data + sizeof(x);
			x ^= k28;
			x = v128_clmul_cross(x);

			x ^= _mm256_extracti128_si256(acc2, 0) ^
			    _mm256_extracti128_si256(acc2, 1);

			memcpy(&oh, &x, sizeof(oh));
		}

		/* Final ENH chunk. */
		{
			__uint128_t enh = (__uint128_t)seed << 64;
			uint64_t x, y;

			memcpy(&x, data, sizeof(x));
			data = (const char *)data + sizeof(x);
			memcpy(&y, data, sizeof(y));
			data = (const char *)data + sizeof(y);

			x += kx;
			y += ky;
			enh += (__uint128_t)x * y;

			oh.bits[0] ^= (uint64_t)enh;
			oh.bits[1] ^= (uint64_t)(enh >> 64) ^ (uint64_t)enh;
		}

		ret = horner_double_update(ret, m0, m1, oh.bits[0], oh.bits[1]);
	} while (--n_blocks);

	return ret;
}
#endif
