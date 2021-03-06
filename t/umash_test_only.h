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
 * Compresses one OH block of 256 bytes.
 */
struct umash_oh oh_one_block(const uint64_t *params, uint64_t tag, const void *block);

/**
 * Compress the last OH block of up to 256 bytes.  `block + n_bytes -
 * 16` must contain input data.
 */
struct umash_oh oh_last_block(
    const uint64_t *params, uint64_t tag, const void *block, size_t n_bytes);

/**
 * Converts a buffer of <= 8 bytes to a 64-bit integers.
 */
uint64_t vec_to_u64(const void *data, size_t n_bytes);

/**
 * Hashes up to 8 bytes of data with a pseudo-random permutation.
 */
uint64_t umash_short(
    const uint64_t *params, uint64_t seed, const void *data, size_t n_bytes);

/**
 * Invertibly mixes the bits of `x`.
 */
uint64_t finalize(uint64_t x);

/**
 * Hashes 9-16 bytes of data with one overlapped iteration of OH (i.e., NH).
 *
 * @param multipliers is {f^2, f} reduced mod 2**61 - 1, where f is the seed.
 */
uint64_t umash_medium(const uint64_t multipliers[static 2], const uint64_t *oh,
    uint64_t seed, const void *data, size_t n_bytes);

/**
 * Hashes 16 or more bytes of data with OH feeding into a polynomial hash.
 *
 * @param multipliers is {f^2, f} reduced mod 2**61 - 1, where f is the seed.
 */
uint64_t umash_long(const uint64_t multipliers[static 2], const uint64_t *oh,
    uint64_t seed, const void *data, size_t n_bytes);

/**
 * Fills `dst[0 ... len)` with the Salsa20 stream cipher.
 */
void salsa20_stream(
    void *dst, size_t len, const uint8_t nonce[static 8], const uint8_t key[static 32]);
#endif /* !UMASH_TEST_ONLY_H */
