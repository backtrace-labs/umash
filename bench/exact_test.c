#include "exact_test.h"

#include <stdlib.h>

#include "xoshiro.h"

#define FAIL(MSG) FAIL_(MSG, __FILE__, __LINE__)
#define FAIL_(MSG, FILE, LINE) FAIL__(MSG, FILE, LINE)
#define FAIL__(MSG, FILE, LINE) (*error = (MSG " @" FILE ":" #LINE), false)

#define COND_OR_FAIL(CONDITION, ...) COND_OR_FAIL_(CONDITION, __VA_ARGS__)
#define COND_OR_FAIL_(CONDITION, MSG, ...)                             \
	do {                                                           \
		if (!(CONDITION))                                      \
			return FAIL(#CONDITION " is false (" MSG ")"); \
	} while (0)

struct xoshiro *
exact_test_prng_create(void)
{
	struct xoshiro *ret;

	ret = malloc(sizeof(*ret));
	*ret = xoshiro_get();
	return ret;
}

void
exact_test_prng_destroy(struct xoshiro *prng)
{

	free(prng);
	return;
}

/**
 * Use a fixed point 64.64 multiplication to generate a value in [0,
 * limit).
 */
static size_t
xoshiro_below(struct xoshiro *prng, size_t limit)
{
	__uint128_t product;

	product = xoshiro_next(prng);
	product *= limit;
	return product >> 64;
}

/**
 * Generates a random permutation of `sample_size` values from
 * `observations[0 .. total_size - 1]`.
 *
 * On exit, that permutation is in `observations[0 ... sample_size - 1]`.
 */
static void
fisher_yates_shuffle(
    struct xoshiro *prng, uint64_t *observations, size_t sample_size, size_t total_size)
{

	for (size_t i = 0; i < sample_size; i++) {
		size_t pick;
		uint64_t x_i, x_pick;

		pick = i + xoshiro_below(prng, total_size - i);
		x_i = observations[i];
		x_pick = observations[pick];
		observations[i] = x_pick;
		observations[pick] = x_i;
	}

	return;
}

/**
 * We have a tentative pseudorandom split in `observations`: the first
 * values are in class A, and the remaining in class B.
 *
 * Now, we must enforce the probability that values in A are lower
 * than in C.
 */
static void
conditional_flips(struct xoshiro *prng, uint64_t *observations, size_t to_flip,
    size_t offset, double p_a_lower)
{
	double scaled_probability = p_a_lower * UINT64_MAX;
	uint64_t threshold =
	    (scaled_probability < UINT64_MAX) ? scaled_probability : UINT64_MAX;

	/*
	 * We'll match the first `to_flip` values with values `offset`
	 * away, and randomly assign the min/max value to the lowest
	 * index (class A) with a biased coin flip.
	 *
	 * We know the first `to_flip` values are all in class A, since
	 * `to_flip = min(m, n)`.  We also know the values starting at
	 * `offset = max(m, n)` are in class B, and that
	 * `to_flip + offset = min(m, n) + max(m, n) = m + n` doesn't
	 * go past the end of the `observations` array.
	 */
	for (size_t i = 0; i < to_flip; i++) {
		uint64_t x_a = observations[i];
		uint64_t x_b = observations[i + offset];
		uint64_t min_x = (x_a < x_b) ? x_a : x_b;
		uint64_t max_x = (x_a < x_b) ? x_b : x_a;

		if (xoshiro_next(prng) < threshold) {
			observations[i] = min_x;
			observations[i + offset] = max_x;
		} else {
			observations[i] = max_x;
			observations[i + offset] = min_x;
		}
	}

	return;
}

bool
exact_test_shuffle(struct xoshiro *prng_state, uint64_t *observations, size_t m, size_t n,
    double p_a_lower, const char **error)
{
	struct xoshiro prng;
	size_t min_count = (m < n) ? m : n;
	size_t max_count = (m > n) ? m : n;

	COND_OR_FAIL(m + n >= n, "total size must not overflow");

	/*
	 * Work with the current PRNG state, and advance the caller's
	 * state by 2^128 to ensure runs don't overlap or otherwise
	 * affect each other.
	 */
	prng = xoshiro_jump(prng_state);

	fisher_yates_shuffle(&prng, observations, max_count, m + n);
	COND_OR_FAIL(p_a_lower == p_a_lower, "must not be NaN");
	COND_OR_FAIL(p_a_lower >= 0);
	COND_OR_FAIL(p_a_lower <= 1.0);

	if (p_a_lower != 0.5)
		conditional_flips(&prng, observations, min_count, max_count, p_a_lower);

	return true;
}

static int
cmp_u64(const void *vx, const void *vy)
{
	const uint64_t *x = vx;
	const uint64_t *y = vy;

	if (*x == *y)
		return 0;

	return (*x < *y) ? -1 : 1;
}

void
exact_test_offset_sort(
    uint64_t *observations, size_t m, size_t n, uint64_t a_offset, uint64_t b_offset)
{
	uint64_t shifted_a_offset = 2 * a_offset;
	uint64_t shifted_b_offset = 2 * b_offset + 1;

	for (size_t i = 0; i < m; i++)
		observations[i] = 2 * observations[i] + shifted_a_offset;

	for (size_t i = m; i < m + n; i++)
		observations[i] = 2 * observations[i] + shifted_b_offset;

	qsort(observations, m + n, sizeof(uint64_t), cmp_u64);
	return;
}

double
exact_test_gt_prob(const uint64_t *observations, size_t m, size_t n)
{
	__uint128_t acc = 0;
	/*
	 * Number of values in B class `< observations[i]`.
	 *
	 * This value is temporarily off when updating the span of
	 * values in B that are exactly equal to `observations[i]`,
	 * but the discrepancy is irrelevant since we break ties by
	 * letting values from class A come first.
	 */
	uint64_t b_count = 0;

	for (size_t i = 0, total = m + n; i < total; i++) {
		bool class_a = (observations[i] & 1) == 0;

		if (class_a) {
			acc += b_count;
		} else {
			b_count++;
		}
	}

	return acc / (1.0 * m * n);
}

double
exact_test_lte_prob(const uint64_t *observations, size_t m, size_t n)
{

	return 1.0 - exact_test_gt_prob(observations, m, n);
}
