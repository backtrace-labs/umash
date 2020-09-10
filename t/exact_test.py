from collections import defaultdict, namedtuple
import math
import sys

from csm import csm
from exact_test_sampler import (
    Sample,
    Statistic,
    actual_data_results,
    resampled_data_results,
)

__all__ = [
    "exact_test",
    "lte_prob",
    "gt_prob",
    "mean",
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


DEFAULT_STATISTIC = Statistic(None, 0.5, 0, 0, None, ())


def lte_prob(name, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a statistic that computes the probability that a value
    chosen uniformly at random from A is <= a value uniformly chosen from
    B."""
    return DEFAULT_STATISTIC._replace(
        name=name,
        probability_a_lower=p_a_lower,
        a_offset=a_offset,
        b_offset=b_offset,
        fn_name="exact_test_lte_prob",
        fn_args=(),
    )


def gt_prob(name, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a statistic that computes the probability that a value
    chosen uniformly at random from A is > a value uniformly chosen from
    B."""
    return DEFAULT_STATISTIC._replace(
        name=name,
        probability_a_lower=p_a_lower,
        a_offset=a_offset,
        b_offset=b_offset,
        fn_name="exact_test_gt_prob",
        fn_args=(),
    )


def mean(name, truncate_tails=0.0, p_a_lower=0.5, a_offset=0, b_offset=0):
    """Returns a statistic that computes the difference between the
    (potentially truncated) arithmetic means of A and B.

    If truncate_tail > 0, we remove that fraction (rounded up) of the
    observations at both tails.  For example, truncate_tail=0.01 considers
    only the most central 98% of the data points in the mean.
    """
    return DEFAULT_STATISTIC._replace(
        name=name,
        probability_a_lower=p_a_lower,
        a_offset=a_offset,
        b_offset=b_offset,
        fn_name="exact_test_truncated_mean_diff",
        fn_args=(truncate_tails,),
    )


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

    # Convert defaultdicts to regular dicts, for pickling.
    def undefaultdict(x):
        if not isinstance(x, defaultdict):
            return x
        return {k: undefaultdict(v) for k, v in x.items()}

    return undefaultdict(plan)


ResultAccumulator = namedtuple(
    "ResultAccumulator", ["trials", "lte_actual", "gte_actual"]
)

INITIAL_RESULT_ACCUMULATOR = ResultAccumulator(0, 0, 0)


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

    if len(statistics) != len({stat.name for stat in statistics}):
        raise "Statistics' names must be unique."

    actual_data = Sample(a, b)
    num_stats = len(statistics)
    # Apply a fudged Bonferroni correction for the two-sided quantile
    # test we perform on each statistic.
    eps /= 2 * num_stats * 1.1
    # And use up some of the extra headroom for errors in the inner
    # Bernoulli tests.
    log_inner_eps = math.log(eps / 10)

    actual_stats = actual_data_results(actual_data, statistics)
    if log:
        print("actual: %s" % actual_stats, file=log)
    accumulators = {name: INITIAL_RESULT_ACCUMULATOR for name in actual_stats}

    ret = dict()

    def group_unfathomed_statistics():
        return _group_statistics_in_plan(
            [stat for stat in statistics if stat.name not in ret]
        )

    seen = 0
    test_every = 250
    for sample in resampled_data_results(actual_data, group_unfathomed_statistics):
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
