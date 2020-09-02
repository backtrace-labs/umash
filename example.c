#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "umash.h"

static const char my_secret[32] = "hello example.c";
static struct umash_params my_params;

int
main(int argc, char **argv)
{
	const char *input = "default input";
	struct umash_fp fprint;
	size_t input_size;
	uint64_t seed = 42;
	uint64_t hash;

	umash_params_derive(&my_params, 0, my_secret);

	if (argc > 1)
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
