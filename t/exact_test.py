from collections import defaultdict, namedtuple
import cffi
import math
import os
import sys

from csm import csm
from cffi_util import read_stripped_header

__all__ = [
    "exact_test",
    "quantile",
    "median",
    "q99",
]


# exact_test returns a dict of Statistic name to Result.
# The `actual_value` is the value of the statistic on the sample data
# `m` and `n` are the size of each class
# `judgement` is -1 if the actual value is lower than the resampled ones,
#    1 if higher, 0 if we can't say
# `num_trials` is the number of resampling iterations we needed to find
#    this out.
Result = namedtuple("Result", ["actual_value", "judgement", "m", "n", "num_trials"])


# A statistic has a name, and is defined by the preprocessing for the
# data under the null (probability that values from A is lower than
# that from B [likely not quite what one expects], and offsets to add
# to the u63 values for A and B), by the C statistic computation
# function, and by any additional argument for that function.
Statistic = namedtuple(
    "Statistic",
    ["name", "probability_a_lower", "a_offset", "b_offset", "fn_name", "fn_args"],
)

DEFAULT_STATISTIC = Statistic(None, 0.5, 0, 0, None, ())


def quantile(name, q, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a Statistic that computes the difference between the qth
    quantile of A and B, where 0 <= q <= 1.
    """
    return DEFAULT_STATISTIC._replace(
        name=name,
        probability_a_lower=p_a_lower,
        a_offset=a_offset,
        b_offset=b_offset,
        fn_name="exact_test_quantile_diff",
        fn_args=(q,),
    )


def median(name, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a Statistic that computes the difference between the
    medians of A and B."""
    return quantile(name, 0.5, p_a_lower, a_offset, b_offset)


def q99(name, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a Statistic that computes the difference between the 99th
    percentile of A and B."""
    return quantile(name, 0.99, p_a_lower, a_offset, b_offset)


# We internally group statistics in order to reuse generated data when
# possible.
def _group_statistics_in_plan(statistics):
    """Groups statistics in a trie, by probability_a_lower, then by
    [ab]_offset.

    This structure reflects the execution order when using exact_test.h."""
    plan = defaultdict(lambda: defaultdict(list))
    for stat in statistics:
        p_a_lower = stat.probability_a_lower
        offsets = (stat.a_offset, stat.b_offset)
        plan[p_a_lower][offsets].append(stat)

    return plan


SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

EXACT_HEADERS = ["bench/exact_test.h"]

FFI = cffi.FFI()


for header in EXACT_HEADERS:
    FFI.cdef(read_stripped_header(TOPLEVEL + header))

try:
    EXACT = FFI.dlopen(TOPLEVEL + "/exact.so")
except Exception as e:
    print("Failed to load exact.so: %s" % e)
    EXACT = None


Sample = namedtuple("Sample", ["a_class", "b_class"])


def _actual_data_results(sample, statistics):
    """Computes the actual sample value for all `statistics`, for the
    sample values in `sample.a_class` and `sample.b_class`.
    """
    a = sample.a_class
    b = sample.b_class

    def _make_buf():
        buf = FFI.new("uint64_t[]", len(a) + len(b))
        for i, x in enumerate(a + b):
            buf[i] = x
        return buf

    results = dict()
    m = len(a)
    n = len(b)
    buf = _make_buf()
    total = m + n
    copy = FFI.new("uint64_t[]", total)
    FFI.memmove(copy, buf, total * FFI.sizeof("uint64_t"))

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, copy, m, n, 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)

    for stat in statistics:
        value = getattr(EXACT, stat.fn_name)(copy, m, n, *stat.fn_args)
        results[stat.name] = value
    return results


def _resampled_data_results(sample, grouped_statistics):
    """Yields values for all the statistics in `grouped_statistics` after
    shuffling values from `sample.a_class` and `sample.b_class`.
    """

    a = sample.a_class
    b = sample.b_class

    def _make_buf():
        buf = FFI.new("uint64_t[]", len(a) + len(b))
        for i, x in enumerate(a + b):
            buf[i] = x
        return buf

    m = len(a)
    n = len(b)
    buf = _make_buf()
    total = m + n
    shuffled_buf = FFI.new("uint64_t[]", total)
    sorted_buf = FFI.new("uint64_t[]", total)
    error_ptr = FFI.new("char**")
    xoshiro = EXACT.exact_test_prng_create()

    def compute_results():
        results = dict()
        for p_a_lt, stats_for_p in grouped_statistics.items():
            FFI.memmove(shuffled_buf, buf, total * FFI.sizeof("uint64_t"))
            if not EXACT.exact_test_shuffle(
                xoshiro, shuffled_buf, m, n, p_a_lt, error_ptr
            ):
                raise "Shuffle failed: %s" % str(FFI.string(error_ptr[0]), "utf-8")

            for (a_offset, b_offset), stats_for_offset in stats_for_p.items():
                FFI.memmove(sorted_buf, shuffled_buf, total * FFI.sizeof("uint64_t"))
                EXACT.exact_test_offset_sort(
                    xoshiro, sorted_buf, m, n, a_offset, b_offset
                )
                for stat in stats_for_offset:
                    results[stat.name] = getattr(EXACT, stat.fn_name)(
                        sorted_buf, m, n, *stat.fn_args
                    )
        return results

    try:
        while True:
            yield compute_results()
    finally:
        EXACT.exact_test_prng_destroy(xoshiro)


ResultAccumulator = namedtuple(
    "ResultAccumulator", ["trials", "lte_actual", "gte_actual"], defaults=[0, 0, 0]
)


def _significance_test(
    ret,
    eps,
    log_inner_eps,
    name,
    monte_carlo_value,
    actual_data,
    actual,
    lte_actual,
    gte_actual,
    trials,
    log,
):
    """Performs a CSM test for `name`, with `lte_actual` Monte Carlo
    values less than or equal to the actual sample value and
    `gte_actual` greater than or equal, over a total of `trials`
    iterations.

    If a statistically significant result is found, writes it to
    `ret`.
    """
    lt_significant, lt_level = csm(trials, eps, lte_actual, log_inner_eps)
    gt_significant, gt_level = csm(trials, eps, gte_actual, log_inner_eps)

    if log:
        print(
            "%i\t%s:\t%i\t%i\t(%f %f / %f)"
            % (
                trials,
                name,
                lte_actual,
                gte_actual,
                max(lt_level, gt_level),
                monte_carlo_value,
                actual,
            ),
            file=log,
        )

    partial_result = Result(
        actual, None, len(actual_data.a_class), len(actual_data.b_class), trials
    )
    count_in_middle = 0
    if lt_significant:
        # We're pretty sure the actual stat is too low to
        # realistically happen under then null
        if lte_actual / trials < eps:
            ret[name] = partial_result._replace(judgement=-1)
            return
        count_in_middle += 1

    if gt_significant:
        # We're pretty sure the actual stat is too high.
        if gte_actual / trials < eps:
            ret[name] = partial_result._replace(judgement=1)
            return
        count_in_middle += 1

    if count_in_middle == 2:
        # We're sure the actual stat isn't too low nor too
        # high for the null.
        ret[name] = partial_result._replace(judgement=0)


def exact_test(
    a, b, statistics, eps=1e-4, log=sys.stderr,
):
    """Performs an exact significance test for every statistic in
    `statistics`, on u63-valued observations in a and b, with false
    positive rate eps.

    Returns a dict of results.  For each statistic, the result will
    have one entry mapping the statistic's name to a Result.
    """

    if not statistics:
        return dict()

    actual_data = Sample(a, b)
    num_stats = len(statistics)
    # Apply a fudged Bonferroni correction for the two-sided quantile
    # test we perform on each statistic.
    eps /= 2 * num_stats * 1.1
    # And use up some of the extra headroom for errors in the inner
    # Bernoulli tests.
    log_inner_eps = math.log(eps / 10)

    actual_stats = _actual_data_results(actual_data, statistics)
    if log:
        print("actual: %s" % actual_stats, file=log)
    accumulators = dict()
    for stat_name in actual_stats:
        accumulators[stat_name] = ResultAccumulator()

    ret = dict()

    seen = 0
    test_every = 250
    for sample in _resampled_data_results(
        actual_data, _group_statistics_in_plan(statistics)
    ):
        for name, stat in sample.items():
            actual = actual_stats[name]
            current = accumulators[name]
            if stat <= actual:
                current = current._replace(lte_actual=current.lte_actual + 1)
            if stat >= actual:
                current = current._replace(gte_actual=current.gte_actual + 1)

            accumulators[name] = current._replace(trials=current.trials + 1)

        seen += 1
        if (seen % test_every) != 0:
            continue

        if seen >= 40 * test_every:
            test_every *= 10
        for name, acc in accumulators.items():
            if name in ret:  # We already have a result -> skip
                continue
            _significance_test(
                ret,
                eps,
                log_inner_eps,
                name,
                sample[name],
                actual_data,
                actual_stats[name],
                acc.lte_actual,
                acc.gte_actual,
                acc.trials,
                log,
            )
        if len(ret) == len(actual_stats):
            return {name: ret[name] for name in actual_stats}
