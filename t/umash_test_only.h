#ifndef UMASH_TEST_ONLY_H
#define UMASH_TEST_ONLY_H
/**
 * The prototypes in this header file are only exposed for testing,
 * when UMASH is built with -DUMASH_TEST_ONLY.
 */

#ifndef UMASH_TEST_ONLY
#error "umash_test_only.h should only be used with -DUMASH_TEST_ONLY"
#endif

/**
 * Computes z \equiv (x + y)    \mod 2^{64} - 8,
 * assuming x + y < 2^{65} - 8.
 *
 * In practice, we always call this with `y < 2^{64} - 8`.
 */
uint64_t add_mod_fast(uint64_t x, uint64_t y);

/**
 * Computes z = (x + y) % (2^{64} - 8).
 */
uint64_t add_mod_slow(uint64_t x, uint64_t y);

/**
 * Computes z \equiv mx    \mod 2^{64} - 8,
 * assuming m < 2**61 - 1.
 *
 * The implementation works as long as mx < 2**125.
 */
uint64_t mul_mod_fast(uint64_t m, uint64_t x);

/**
 * Computes (m0 (acc + x) + m1 y) % (2^{64} - 8).
 *
 * @param acc integer < 2**64 - 8
 * @param m0, m1 multipliers < 2**61 - 1
 */
uint64_t horner_double_update(
    uint64_t acc, uint64_t m0, uint64_t m1, uint64_t x, uint64_t y);

/**
 * Compresses one PH block of 256 bytes, with the accumulator
 * initialised to `seed`.
 */
struct umash_ph ph_one_block(
    const uint64_t *params, uint64_t seed, const void *block);

/**
 * Compress the last PH block of up to 256 bytes.  `block + n_bytes -
 * 16` must contain input data.
 */
struct umash_ph ph_last_block(
    const uint64_t *params, uint64_t seed, const void *block, size_t n_bytes);
#endif /* !UMASH_TEST_ONLY_H */
