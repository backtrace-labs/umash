import math
from csm import csm
from umash import BENCH
from umash import BENCH_FFI as FFI


def _exact_test_result(buf, m, n, stat_fn):
    """Computes the actual sample value for `stat_fn`, for the sample
    values in `buf`, with `m` values from class A followed by `n` from
    class B.
    """
    total = m + n
    copy = FFI.new("uint64_t[]", total)
    xoshiro = BENCH.exact_test_prng_create()
    try:
        FFI.memmove(copy, buf, total * FFI.sizeof("uint64_t"))
        BENCH.exact_test_offset_sort(xoshiro, copy, m, n, 0, 0)
        return stat_fn(copy, m, n)
    finally:
        BENCH.exact_test_prng_destroy(xoshiro)


def _resample_exact_test_results(buf, m, n, stat_fn, p_a_lt, a_offset, b_offset):
    """Yields values computed by `stat_fn` after shuffling (copies of)
    `buf`, with `m` values from class A and `n` from class B.
    """
    total = m + n
    copy = FFI.new("uint64_t[]", total)
    error_ptr = FFI.new("char**")
    xoshiro = BENCH.exact_test_prng_create()
    try:
        while True:
            FFI.memmove(copy, buf, total * FFI.sizeof("uint64_t"))
            if not BENCH.exact_test_shuffle(xoshiro, copy, m, n, p_a_lt, error_ptr):
                raise "Shuffle failed: %s" % str(error_ptr[0], "utf-8")
            BENCH.exact_test_offset_sort(xoshiro, copy, m, n, a_offset, b_offset)
            yield stat_fn(copy, m, n)
    finally:
        BENCH.exact_test_prng_destroy(xoshiro)


def exact_test(a, b, statistic="lte", eps=1e-6, p_a_lt=0.5, a_offset=0, b_offset=0):
    """Performs an exact significance test on u63-valued observations in a
    and b, with false positive rate eps.

    Returns -1 if we find that the statistic for A is probably lower
    than what we would expect under the null, 1 if greater, and 0 if
    we definitely can't tell the difference.

    The default statistic, "lte", computes the sample probability that
    a value in a is less than or equal to one in b.

    We compare the statistic value for the sample with ones generated
    by shuffling the sample data, according to the null hypothesis
    described by p_a_lt, or by a_offset, and b_offset.

    When p_a_lt differs from 0.5, it specifies the probability that
    values in a are less than values in b (with ties broken
    arbitrarily), in the resampled null hypothesis generator.

    a_offset is added to values assigned to sample a in the null
    hypothesis generator; b_offset is added to values assigned to
    sample b.

    Combining p_a_lt and a_offset/b_offset might not make sense:
    p_a_lt is applied first, followed by a_offset / b_offset.
    """

    def _make_buf():
        buf = FFI.new("uint64_t[]", len(a) + len(b))
        for i, x in enumerate(a + b):
            buf[i] = x
        return buf

    if statistic in ("lte", "<="):
        stat_fn = BENCH.exact_test_lte_prob
    elif stat_fn in ("gt", ">"):
        stat_fn = BENCH.exact_test_gt_prob
    else:
        raise "Unknown statistic fn %s" % statistic

    m = len(a)
    n = len(b)

    # Apply a fudged Bonferroni correction for the two-sided quantile
    # test.
    eps /= 2 * 1.1
    # And use up some of the extra headroom for errors in the inner
    # Bernoulli test.
    log_inner_eps = math.log(eps / 10)

    trials = 0
    lte_actual = 0
    gte_actual = 0

    test_every = 10
    buf = _make_buf()
    actual_stat = _exact_test_result(buf, m, n, stat_fn)
    print("actual: %f" % actual_stat)

    for stat in _resample_exact_test_results(
        buf, m, n, stat_fn, p_a_lt, a_offset, b_offset
    ):
        if stat <= actual_stat:
            lte_actual += 1
        if stat >= actual_stat:
            gte_actual += 1
        trials += 1

        if (trials % test_every) != 0:
            continue

        if trials >= 100 * test_every:
            test_every *= 10
        count_in_middle = 0
        lt_significant, lt_level = csm(trials, eps, lte_actual, log_inner_eps)
        gt_significant, gt_level = csm(trials, eps, gte_actual, log_inner_eps)

        print(
            "%i: %i %i (%f %f / %f)"
            % (
                trials,
                lte_actual,
                gte_actual,
                max(lt_level, gt_level),
                stat,
                actual_stat,
            )
        )
        if lt_significant:
            # We're pretty sure the actual stat is too low to
            # realistically happen under then null
            if lte_actual / trials < eps:
                return -1, trials
            count_in_middle += 1

        if gt_significant:
            # We're pretty sure the actual stat is too high.
            if gte_actual / trials < eps:
                return 1, trials
            count_in_middle += 1

        if count_in_middle == 2:
            # We're sure the actual stat isn't too low nor too
            # high for the null.
            return 0, trials


# In [1]: import random
# In [2]: import math
# In [3]: import exact_test
# In [4]: A = [max(0, math.ceil(random.normalvariate(1000, 10))) for _ in range(10000)]
# In [5]: B = [max(0, math.ceil(random.normalvariate(1001, 10))) for _ in range(10000)]
# In [6]: exact_test.exact_test(A, B, eps=1e-4)
# actual: 0.543088
# 10: 10 0 (2.397441 0.508931 / 0.543088)
# 20: 20 0 (3.043613 0.502342 / 0.543088)
# ...
# 560000: 560000 0 (-12.219430 0.504535 / 0.543088)
# 570000: 570000 0 (-12.656286 0.513219 / 0.543088)
# Out[6]: (1, 570000)
