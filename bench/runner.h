#pragma once
/**
 * This header provides benchmarking wrappers that may be used to
 * evaluate the latency to compute UMASH hashes or fingerprints
 * of different sizes.
 */

#include <stddef.h>
#include <stdint.h>

#ifndef VERSION_SUFFIX
#define VERSION_SUFFIX
#endif

/*
 * We use the option struct defined in the current tree for all
 * benchmarking libraries.  The options struct must be updated in an
 * ABI compatible way.  In the common case, this is as simple as
 * only adding fields at the end.
 */
struct bench_individual_options {
	size_t size; /* sizeof(struct bench_individual_options) */
};

/*
 * We rename extern symbols with an explicit version suffix to make it
 * easier to load multiple versions in the same process.
 */
#define ID(X) ID_(X, VERSION_SUFFIX)
#define ID_(X, Y) ID__(X, Y)
#define ID__(X, Y) X##Y

/**
 * Returns the aggregate latency to compute `num_trials`
 * UMASH hashes.
 *
 * @param input_len array of input length arguments for umash_full.
 * @param num_trials number of lengths in `input_len`.
 * @param max_len maximum value in `input_len`.
 * @return total cycle count for these umash_full calls, with
 *   precautions taken to prevent OOE from overlapping hashes.
 */
uint64_t ID(umash_bench_aggregate)(
    const size_t *input_len, size_t num_trials, size_t max_len);

/**
 * Returns the aggregate latency to compute `num_trials`
 * UMASH fingerprints.
 *
 * @param input_len array of input length arguments for umash_fprint.
 * @param num_trials number of lengths in `input_len`.
 * @param max_len maximum value in `input_len`.
 * @return total cycle count for these umash_fprint calls, with
 *   precautions taken to prevent OOE from overlapping hashes.
 */
uint64_t ID(umash_bench_fp_aggregate)(
    const size_t *input_len, size_t num_trials, size_t max_len);

/**
 * Evaluates cycle timings for individual UMASH calls
 *
 * @param timings[OUT]: populated with the timing for each corresponding
 *   call in `input_len`.
 * @param input_len: array of input length arguments for umash_full.
 * @param num_trials number of lengths in `input_len`.
 * @param max_len maximum value in `input_len`.
 */
void ID(umash_bench_individual)(const struct bench_individual_options *,
    uint64_t *timings, const size_t *input_len, size_t num_trials, size_t max_len);

/**
 * Evaluates cycle timings for individual UMASH fingerprint calls
 *
 * @param timings[OUT]: populated with the timing for each corresponding
 *   call in `input_len`.
 * @param input_len: array of input length arguments for umash_fprint.
 * @param num_trials number of lengths in `input_len`.
 * @param max_len maximum value in `input_len`.
 */
void ID(umash_bench_fp_individual)(const struct bench_individual_options *,
    uint64_t *timings, const size_t *input_len, size_t num_trials, size_t max_len);
