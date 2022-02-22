#include <assert.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>

#include "umash.h"

static const char my_secret[32] = "umash_all.c";
static struct umash_params my_params;

static double
bench_throughput_1(const void *buf, size_t len)
{
	static const size_t n_iter = 2000;
	struct timeval begin, end;
	/* Create fake data dependencies with this array. */
	const void *bufs[2] = { buf, buf };
	uint64_t hash = 0;
	double elapsed;
	int r;

	r = gettimeofday(&begin, NULL);
	assert(r == 0);

	for (size_t i = 0; i < n_iter; i++) {
		hash = umash_full(&my_params, 0, /*which=*/0, bufs[hash & 1], len);
	}

	r = gettimeofday(&end, NULL);
	assert(r == 0);

	elapsed = (end.tv_sec - begin.tv_sec) + 1e-6 * end.tv_usec - 1e-6 * begin.tv_usec;
	return elapsed / n_iter;
}

static void
bench_throughput(const void *buf, size_t len)
{
	double best = HUGE_VAL;

	for (size_t i = 0; i < 10; i++) {
		double trial;

		trial = bench_throughput_1(buf, len);
		if (trial < best)
			best = trial;
	}

	fprintf(stderr, "Hash time for %zu bytes: %.3f ns (%.6f GB/s)\n", len, best * 1e9,
	    (len / best) / (1024 * 1024 * 1024));
}

static void
umash_one(uint64_t seed, const void *buf, size_t len)
{
	uint64_t hash;

	hash = umash_full(&my_params, seed, /*which=*/0, buf, len);
	printf("%016" PRIx64 "\n", hash);
	return;
}

int
main(int argc, char **argv)
{
	char *buf;
	uint64_t seed = 42;
	size_t n_read;
	int input_size;
	int r;

	umash_params_derive(&my_params, 0, my_secret);

	assert(argc > 1);
	input_size = atoi(argv[1]);
	assert(input_size >= 0);

	r = posix_memalign((void **)&buf, 64, input_size);
	assert(r == 0);

	n_read = fread(buf, input_size, 1, stdin);
	assert(n_read == 1);

	/* Warm it up. */
	(void)umash_full(&my_params, 0, /*which=*/0, buf, input_size);

	bench_throughput(buf, input_size);

	for (size_t len = 0; len < (size_t)input_size; len++) {
		size_t remaining = input_size - len;
		for (size_t offset = 0; offset < 64; offset++) {
			if (offset > remaining)
				continue;

			umash_one(seed, buf + offset, len);
		}

		umash_one(seed, buf + input_size - len, len);
	}
}
