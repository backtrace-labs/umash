#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "umash.h"

static const char my_secret[32] = "hello example.c";
static struct umash_params my_params;

/*  Written in 2019 by David Blackman and Sebastiano Vigna (vigna@acm.org)

To the extent possible under law, the author has dedicated all copyright
and related and neighboring rights to this software to the public domain
worldwide.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR
IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE. */

/* This is xoshiro256++ 1.0, one of our all-purpose, rock-solid generators.
   It has excellent (sub-ns) speed, a state (256 bits) that is large
   enough for any parallel application, and it passes all tests we are
   aware of.

   For generating just floating-point numbers, xoshiro256+ is even faster.

   The state must be seeded so that it is not everywhere zero. If you have
   a 64-bit seed, we suggest to seed a splitmix64 generator and use its
   output to fill s. */

static inline uint64_t
rotl(const uint64_t x, int k)
{
	return (x << k) | (x >> (64 - k));
}

static uint64_t s[4] = {
	/* random.org */
	0x10953162975cae3aUL,
	0x8f55faa335a049c2UL,
	0xd7b63d4a26aa53b8UL,
	0xc6d5924050d5363fUL,
};

static uint64_t
next(void)
{
	const uint64_t result = rotl(s[0] + s[3], 23) + s[0];

	const uint64_t t = s[1] << 17;

	s[2] ^= s[0];
	s[3] ^= s[1];
	s[1] ^= s[2];
	s[0] ^= s[3];

	s[2] ^= t;

	s[3] = rotl(s[3], 45);

	return result;
}

static void
run_range(const char *buf, size_t start_offset, size_t len)
{
	static const uint64_t seeds[] = { 0, 123 };
	const void *start = buf + start_offset;

	for (size_t seed_idx = 0; seed_idx < sizeof(seeds) / sizeof(seeds[0]);
	    seed_idx++) {
		struct umash_fp fprint;
		const uint64_t seed = seeds[seed_idx];
		uint64_t low, high;

		fprint = umash_fprint(&my_params, seed, start, len);
		low = umash_full(&my_params, seed, /*which=*/0, start, len);
		high = umash_full(&my_params, seed, /*which=*/1, start, len);

		if (fprint.hash[0] != low || fprint.hash[1] != high) {
			fprintf(stderr,
			    "Obvious mismatch len=%zu offset=%zu seed=%" PRIu64 ": "
			    "%016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64
			    "\n",
			    len, start_offset, seed, fprint.hash[0], fprint.hash[1], low,
			    high);
		}

		/* Lower case hex, left 0-padded to 16 characters. */
		printf("%016" PRIx64 " %016" PRIx64 " %016" PRIx64 " %016" PRIx64 "\n",
		    fprint.hash[0], fprint.hash[1], low, high);
	}

	return;
}

static int
run_test_set(void)
{
	static const char expected_sum[] =
	    "50fff4f41f27a3464445e47bb270c3e027388198aed8734efdba6460d04a3624";
	static const size_t padding = 512;
	static const size_t max_len = 4 * 256 * 1024;
	static const size_t num_bytes = max_len + padding;
	uint64_t *buf = malloc(num_bytes);
	const char *bytes = (const char *)buf;

	for (size_t i = 0; i < num_bytes / sizeof(uint64_t); i++)
		buf[i] = next();

	fprintf(stderr,
	    "Running %zu test set iterations.  Run as ./example | sha256sum --strict --check <(echo '%s  -')\n",
	    max_len + 1, expected_sum);

	size_t last_offset = 1;
	size_t since_last_print = 0;
	for (size_t len = 0; len <= max_len; len++) {
		if (len <= 4 * 256 * 64) {
			for (size_t offset = 0; offset < padding; offset++)
				run_range(bytes, offset, len);
		} else {
			run_range(bytes, 0, len);

			last_offset = (last_offset + 23) % 511;
			run_range(bytes, last_offset + 1, len);
		}

		since_last_print += len;
		if (since_last_print >= 10 * 1000 * 1000UL || len % 1000 == 999) {
			fprintf(stderr, "iter=%zu\n", len + 1);
			since_last_print = 0;
		}
	}

	fprintf(stderr, "Completed test set.  Expected `./example | sha256sum`: %s\n",
	    expected_sum);

	return 0;
}

int
main(int argc, char **argv)
{
	const char *input = "default input";
	struct umash_fp fprint;
	size_t input_size;
	uint64_t seed = 42;
	uint64_t hash;

	umash_params_derive(&my_params, 0, my_secret);

	if (argc <= 1)
		return run_test_set();

	input = argv[1];
	input_size = strlen(input);
	printf("Input: %s\n", input);

	fprint = umash_fprint(&my_params, seed, input, input_size);
	printf("Fingerprint: %" PRIx64 ", %" PRIx64 "\n", fprint.hash[0], fprint.hash[1]);

	hash = umash_full(&my_params, seed, /*which=*/0, input, input_size);
	printf("Hash 0: %" PRIx64 "\n", hash);

	hash = umash_full(&my_params, seed, /*which=*/1, input, input_size);
	printf("Hash 1: %" PRIx64 "\n", hash);
	return 0;
}
