#include "exact_test.h"

#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

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

/**
 * Updates [*min, *max], an inclusive dense range of values in
 * `observations`.
 *
 * May return an empty interval (min > max).
 */
static void
find_dense_range(struct xoshiro *prng_state, const uint64_t *observations, size_t num,
    uint64_t *min, uint64_t *max)
{
	struct xoshiro prng;
	uint64_t *sample;
	size_t sample_size;
	size_t dense_lo_idx, dense_hi_idx;

	if (*max - *min <= num)
		return;

	prng = xoshiro_jump(prng_state);
	sample_size = 3 + sqrt(num);
	sample = malloc(sample_size * sizeof(*sample));
	sample[0] = *min;
	sample[1] = *min;

	for (size_t i = 2; i < sample_size; i++) {
		size_t idx;

		idx = xoshiro_below(&prng, num);
		sample[i] = observations[idx];
	}

	qsort(sample, sample_size, sizeof(uint64_t), cmp_u64);
	dense_lo_idx = 0;
	dense_hi_idx = sample_size - 1;

	/* If the tentative dense range is too wide... */
	while (sample[dense_hi_idx] - sample[dense_lo_idx] > num) {
		uint64_t gap_lo, gap_hi;

		/*
		 * Greedily advance the index with the widest gap to
		 * the next boundary.
		 */
		gap_lo = sample[dense_lo_idx + 1] - sample[dense_lo_idx];
		gap_hi = sample[dense_hi_idx] - sample[dense_hi_idx - 1];

		/*
		 * Break ties arbitrarily... in our case, prefer to
		 * keep `gap_lo` as is: we most expect outliers at
		 * the high end.
		 */
		if (gap_lo > gap_hi) {
			dense_lo_idx++;
		} else {
			dense_hi_idx--;
		}
	}

	/*
	 * Only store a range if it looks like it covers at least
	 * ~num / 10 points.
	 */
	if (dense_hi_idx - dense_lo_idx >= sample_size / 10) {
		*min = sample[dense_lo_idx];
		*max = sample[dense_hi_idx];
	} else {
		*min = UINT64_MAX;
		*max = 0;
	}

	free(sample);
	return;
}

static size_t
compress_count_sort(size_t *counts, uint64_t *observations, size_t num,
    uint64_t min_dense, uint64_t max_dense)
{
	uint64_t dense_range = max_dense - min_dense;
	size_t num_outliers = 0;

	if (min_dense > max_dense)
		return num;

	for (size_t i = 0; i < num; i++) {
		uint64_t value = observations[i];

		if ((value - min_dense) <= dense_range) {
			counts[value - min_dense]++;
		} else {
			observations[num_outliers++] = value;
		}
	}

	return num_outliers;
}

static void
merge_counts_into_outliers(uint64_t *sorted, const size_t *counts, size_t num_outliers,
    size_t num_total, uint64_t min_dense, uint64_t max_dense)
{
	size_t i;

	/* Easy case: nothing in the dense range. */
	if (num_outliers == num_total)
		return;

	/* Skip outliers < min_dense. */
	for (i = 0; i < num_outliers; i++) {
		if (sorted[i] > min_dense)
			break;
	}

	/* Copy remaining outliers to the end of `sorted`. */
	if (i < num_outliers) {
		size_t tail_outliers = num_outliers - i;

		memmove(sorted + num_total - tail_outliers, sorted + i,
		    tail_outliers * sizeof(sorted[0]));
	}

	/* Splat counts in `sorted[i...]`, */
	for (uint64_t count_idx = 0; count_idx <= max_dense - min_dense; count_idx++) {
		uint64_t value = min_dense + count_idx;
		size_t count = counts[count_idx];

		for (size_t j = 0; j < count; j++)
			sorted[i++] = value;
	}

	return;
}

/**
 * Hybrid counting / comparison sort.
 *
 * We attempt to find the densest range in `observations` that spans
 * `num` or fewer u64.  That range will go to a counting sort pass,
 * while the remaining outliers hit qsort, before joining the two
 * together.
 */
static void
hybrid_sort(
    struct xoshiro *prng, uint64_t *observations, size_t num, uint64_t min, uint64_t max)
{
	size_t *counts;
	size_t num_outliers;

	/* Empty or singleton range -> we're done. */
	if (min >= max || min == max - 1)
		return;

	/* If this is small and not obviously dense, just qsort. */
	if (num < 10 && (max - min) > num) {
		qsort(observations, num, sizeof(uint64_t), cmp_u64);
		return;
	}

	/* The dense range covers at most O(num) values. */
	find_dense_range(prng, observations, num, &min, &max);
	if (min > max) {
		counts = NULL;
	} else {
		counts = calloc(max - min + 1, sizeof(*counts));
	}

	/* Update the `counts` array, which sliding outliers to the left. */
	num_outliers = compress_count_sort(counts, observations, num, min, max);

	qsort(observations, num_outliers, sizeof(uint64_t), cmp_u64);
	merge_counts_into_outliers(observations, counts, num_outliers, num, min, max);
	free(counts);
	return;
}

void
exact_test_offset_sort(struct xoshiro *prng, uint64_t *observations, size_t m, size_t n,
    uint64_t a_offset, uint64_t b_offset)
{
	uint64_t shifted_a_offset = 2 * a_offset;
	uint64_t shifted_b_offset = 2 * b_offset + 1;
	uint64_t min_value = UINT64_MAX;
	uint64_t max_value = 0;

#define OBSERVE(X)                                               \
	do {                                                     \
		min_value = (min_value < (X)) ? min_value : (X); \
		max_value = (max_value > (X)) ? max_value : (X); \
	} while (0)

	for (size_t i = 0; i < m; i++) {
		observations[i] = 2 * observations[i] + shifted_a_offset;
		OBSERVE(observations[i]);
	}

	for (size_t i = m; i < m + n; i++) {
		observations[i] = 2 * observations[i] + shifted_b_offset;
		OBSERVE(observations[i]);
	}

	hybrid_sort(prng, observations, m + n, min_value, max_value);
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

double
exact_test_truncated_mean_diff(
    const uint64_t *observations, size_t m, size_t n, double truncate_frac)
{
	/* Index 0 = class A, 1 = class B. */
	__int128_t sum[2] = { 0 };
	double mean[2];
	size_t count[2];
	size_t start_count[2];
	size_t stop_count[2];
	size_t seen[2] = { 0 };

	if (truncate_frac >= 0.5)
		return nan("");

	start_count[0] = ceil(truncate_frac * m);
	start_count[1] = ceil(truncate_frac * n);
	stop_count[0] = m - start_count[0];
	stop_count[1] = n - start_count[0];

	if (start_count[0] >= stop_count[0] || start_count[1] >= stop_count[1])
		return nan("");

	for (size_t i = 0, total = m + n; i < total; i++) {
		size_t class = observations[i] & 1;
		size_t current_idx = seen[class]++;

		if (current_idx < start_count[class] || current_idx >= stop_count[class])
			continue;

		sum[class] += observations[i] / 2;
	}

	for (size_t class = 0; class < 2; class ++) {
		count[class] = stop_count[class] - start_count[class];

		mean[class] = sum[class] / (1.0 * count[class]);
	}

	/* When things balance nicely, avoid potential cancellation. */
	if (count[0] == count[1])
		return (sum[0] - sum[1]) / (1.0 * count[0]);

	return mean[0] - mean[1];
}
