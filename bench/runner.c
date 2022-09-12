#include "bench/runner.h"

#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <x86intrin.h>

#include "umash.h"

/**
 * We align our hashed buffers for consistency.  We could also accept
 * the alignment as an argument if we ever start looking at code that
 * might be strongly influenced by the hashed data's address.
 */
#define ALLOC_ALIGNMENT 64

/**
 * We build UMASH code in the `umash_code` section, for easy CLFLUSH.
 */
extern const char ID(__start_umash_code)[];
extern const char ID(__stop_umash_code)[];

#define PARAMS_MASK 1
static struct umash_params params[2];

__attribute__((constructor)) static void
setup_params(void)
{

	for (size_t i = 0; i < 2; i++)
		umash_params_derive(&params[i], 42 + i, NULL);
	return;
}

static inline void
cpuid_barrier(void)
{

	asm volatile("cpuid\n\t" ::: "%rax", "%rdx", "%rbx", "%rcx", "memory", "cc");
	return;
}

static __attribute__((__noinline__)) void
flush_code(int level)
{
	uintptr_t begin = (uintptr_t)ID(__start_umash_code);
	uintptr_t end = (uintptr_t)ID(__stop_umash_code);

	if (level == 0)
		return;

	for (uintptr_t addr = begin; addr < end; addr += 64)
		_mm_clflush((void *)addr);

	cpuid_barrier();

	switch (level) {
	case 1:
		for (uintptr_t addr = begin; addr < end; addr += 64)
			_mm_prefetch((void *)addr, _MM_HINT_T1);
		break;
	case 2:
		for (uintptr_t addr = begin; addr < end; addr += 64)
			_mm_prefetch((void *)addr, _MM_HINT_T2);
		break;
	default:
		return;
	}

	cpuid_barrier();
	return;
}

/*
 * We use difference instruction sequences for the beginning and end
 * of the timed sequence because that's what Intel recommends.
 *
 * See "How to Benchmark Code Execution Times on Intel® IA-32 and
 * IA-64 Instruction Set Architectures" by Gabriele Paoloni,
 * https://www.intel.com/content/dam/www/public/us/en/documents/white-papers/ia-32-ia-64-benchmark-code-execution-paper.pdf
 * .
 */

static inline uint64_t
get_ticks_begin(uint64_t *compiler_barrier)
{
	uint32_t lo, hi;

	asm volatile("cpuid\n\t"
		     "rdtsc"
		     : "=a"(lo), "=d"(hi), "+r"(*compiler_barrier)::"%rbx", "%rcx",
		     "memory", "cc");
	return ((uint64_t)hi << 32) | lo;
}

static inline uint64_t
get_ticks_end(void)
{
	uint32_t lo, hi;

	asm volatile("rdtscp\n\t"
		     "mov %%eax, %[lo]\n\t"
		     "mov %%edx, %[hi]\n\t"
		     "cpuid"
		     : [lo] "=r"(lo), [hi] "=r"(hi)::"%rax", "%rdx", "%rbx", "%rcx",
		     "memory", "cc");
	return ((uint64_t)hi << 32) | lo;
}

/**
 * We derive the address of the data to hash by adding a pseudorandom
 * offset obtained by masking the previous hash result with
 * `JITTER_MASK`.
 *
 * Combined with updating the "seed" argument and similarly deriving
 * the "params" struct from the previous hash, this should foil any
 * attempt at overlapping hash computations by the hardware.
 *
 * We do not want to create a similar dependency chain by overwriting
 * the bytes to hash: this ends up creating an unrealistic store
 * forwarding bubble.
 */
#define JITTER_MASK ALLOC_ALIGNMENT

uint64_t ID(umash_bench_aggregate)(
    const size_t *input_len, size_t num_trials, size_t max_len)
{
	size_t bufsz = ALLOC_ALIGNMENT * (1 + (max_len + JITTER_MASK) / ALLOC_ALIGNMENT);
	char *buf;
	uint64_t begin, end;
	uint64_t seed = 0;

	if (posix_memalign((void *)&buf, ALLOC_ALIGNMENT, bufsz) != 0)
		assert(0 && "Failed to allocate buffer.");

	memset(buf, 0x42, max_len + JITTER_MASK);

	begin = get_ticks_begin(&seed);
	seed += begin;
	for (size_t i = 0; i < num_trials; i++) {
		uint64_t hash;

		hash = umash_full(&params[seed & PARAMS_MASK], seed, /*which=*/0,
		    buf + (seed & JITTER_MASK), input_len[i]);
		seed += hash;
	}

	end = get_ticks_end();
	free(buf);
	return end - begin;
}

uint64_t ID(umash_bench_fp_aggregate)(
    const size_t *input_len, size_t num_trials, size_t max_len)
{
	size_t bufsz = ALLOC_ALIGNMENT * (1 + (max_len + JITTER_MASK) / ALLOC_ALIGNMENT);
	char *buf;
	uint64_t begin, end;
	uint64_t seed = 0;

	if (posix_memalign((void *)&buf, ALLOC_ALIGNMENT, bufsz) != 0)
		assert(0 && "Failed to allocate buffer.");

	memset(buf, 0x42, max_len + JITTER_MASK);

	begin = get_ticks_begin(&seed);
	seed += begin;
	for (size_t i = 0; i < num_trials; i++) {
		struct umash_fp fp;
		uint64_t hash;

		fp = umash_fprint(&params[seed & PARAMS_MASK], seed,
		    buf + (seed & JITTER_MASK), input_len[i]);
		hash = fp.hash[0] ^ fp.hash[1];
		seed += hash;
	}

	end = get_ticks_end();
	free(buf);
	return end - begin;
}

static struct bench_individual_options
normalize_options(const struct bench_individual_options *options)
{
	struct bench_individual_options ret = {
		.size = sizeof(ret),
	};

	if (options == NULL)
		return ret;

	if (options->size < ret.size) {
		memcpy(&ret, options, options->size);
	} else {
		memcpy(&ret, options, sizeof(ret));
	}

	ret.size = sizeof(ret);
	return ret;
}

void ID(umash_bench_individual)(const struct bench_individual_options *options_ptr,
    uint64_t *restrict timings, const size_t *input_len, size_t num_trials,
    size_t max_len)
{
	struct bench_individual_options options;
	size_t bufsz = ALLOC_ALIGNMENT * (1 + (max_len + JITTER_MASK) / ALLOC_ALIGNMENT);
	char *buf;
	uint64_t seed = 0;

	options = normalize_options(options_ptr);
	if (posix_memalign((void *)&buf, ALLOC_ALIGNMENT, bufsz) != 0)
		assert(0 && "Failed to allocate buffer.");

	memset(buf, 0x42, max_len + JITTER_MASK);

	for (size_t i = 0; i < num_trials; i++) {
		uint64_t begin, end;
		uint64_t hash;

		flush_code(options.flush_code);
		begin = get_ticks_begin(&seed);
		seed += begin;

		hash = umash_full(&params[seed & PARAMS_MASK], seed, /*which=*/0,
		    buf + (seed & JITTER_MASK), input_len[i]);

		end = get_ticks_end();
		seed += hash + end;

		timings[i] = end - begin;
	}

	free(buf);
	return;
}

void ID(umash_bench_fp_individual)(const struct bench_individual_options *options_ptr,
    uint64_t *restrict timings, const size_t *input_len, size_t num_trials,
    size_t max_len)
{
	struct bench_individual_options options;
	size_t bufsz = ALLOC_ALIGNMENT * (1 + (max_len + JITTER_MASK) / ALLOC_ALIGNMENT);
	char *buf;
	uint64_t seed = 0;

	options = normalize_options(options_ptr);
	if (posix_memalign((void *)&buf, ALLOC_ALIGNMENT, bufsz) != 0)
		assert(0 && "Failed to allocate buffer.");

	memset(buf, 0x42, max_len + JITTER_MASK);

	for (size_t i = 0; i < num_trials; i++) {
		struct umash_fp fp;
		uint64_t begin, end;
		uint64_t hash;

		flush_code(options.flush_code);
		begin = get_ticks_begin(&seed);
		seed += begin;

		fp = umash_fprint(&params[seed & PARAMS_MASK], seed,
		    buf + (seed & JITTER_MASK), input_len[i]);

		end = get_ticks_end();
		hash = fp.hash[0] ^ fp.hash[1];
		seed += hash + end;

		timings[i] = end - begin;
	}

	free(buf);
	return;
}
