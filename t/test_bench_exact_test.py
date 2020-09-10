"""
Test the exact statistical testing code (its internals, mostly).
"""
import math
import pytest
import random
import hypothesis
from hypothesis import assume, given
import hypothesis.strategies as st
from exact_test import (
    Sample,
    exact_test,
    gt_prob,
    median,
    mean,
    q99,
)
from exact_test_sampler import EXACT, FFI, actual_data_results


def u63_lists(min_size=0):
    def make_list(length, min_value, max_value, random):
        min_value, max_value = sorted((min_value, max_value))
        return [random.randint(min_value, max_value) for _ in range(length)]

    long_lists = st.builds(
        make_list,
        st.integers(min_value=min_size, max_value=1000),
        st.integers(min_value=0, max_value=10000),
        st.integers(min_value=0, max_value=10000),
        st.randoms(use_true_random=True),
    )
    dense_lists = st.builds(
        make_list,
        st.integers(min_value=min_size, max_value=1000),
        st.just(10),
        st.just(12),
        st.randoms(use_true_random=True),
    )
    sparse_lists = st.builds(
        make_list,
        st.integers(min_value=min_size, max_value=1000),
        st.just(0),
        st.just(2 ** 63 - 1),
        st.randoms(use_true_random=True),
    )
    return (
        st.lists(st.integers(min_value=0, max_value=2 ** 63 - 1), min_size=min_size)
        | long_lists
        | dense_lists
        | sparse_lists
    )


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(a=u63_lists(), b=u63_lists(), p_a_lower=st.floats(min_value=0.0, max_value=1.0))
def test_shuffle(a, b, p_a_lower):
    expected = sorted(a + b)
    total = len(a) + len(b)
    buf = FFI.new("uint64_t[]", total)
    for i, x in enumerate(a + b):
        buf[i] = x
    # Shuffling `buf` should yield a permutation of `a + b`
    xoshiro = EXACT.exact_test_prng_create()
    err_ptr = FFI.new("char **")
    assert EXACT.exact_test_shuffle(
        xoshiro, buf, len(a), len(b), p_a_lower, err_ptr
    ), "Shuffle failed: %s" % str(FFI.string(err_ptr[0]), "utf-8")
    EXACT.exact_test_prng_destroy(xoshiro)

    actual = sorted([buf[i] for i in range(total)])
    assert expected == actual


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(values=u63_lists())
def test_offset_sort(values):
    expected = sorted([2 * x for x in values])
    buf = FFI.new("uint64_t[]", len(values))
    for i, x in enumerate(values):
        buf[i] = x
    # Sort `len(values)` sampled values from A, and none from B.
    # That's the same as sorting the values shifted left by 1 bit.
    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, buf, len(values), 0, 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)

    actual = [buf[i] for i in range(len(values))]
    assert expected == actual


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    a=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=10),
    b=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=10),
)
def test_gt_prob(a, b):
    """Test gt_prob: the probability that a value from a is strictly
    greater than a value from b.
    """

    expected = sum(x > y for x in a for y in b) / (len(a) * len(b))

    total = len(a) + len(b)
    buf = FFI.new("uint64_t[]", total)
    for i, x in enumerate(a + b):
        buf[i] = x

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, buf, len(a), len(b), 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)
    actual = EXACT.exact_test_gt_prob(buf, len(a), len(b))
    assert abs(expected - actual) < 1e-8


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    a=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=10),
    b=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=10),
)
def test_lte_prob(a, b):
    """Test lte_prob: the probability that a value from a is less than or
    equal to a value from b.
    """

    expected = sum(x <= y for x in a for y in b) / (len(a) * len(b))

    total = len(a) + len(b)
    buf = FFI.new("uint64_t[]", total)
    for i, x in enumerate(a + b):
        buf[i] = x

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, buf, len(a), len(b), 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)
    actual = EXACT.exact_test_lte_prob(buf, len(a), len(b))
    assert abs(expected - actual) < 1e-8


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    a=st.lists(st.integers(min_value=0, max_value=1000), min_size=1),
    b=st.lists(st.integers(min_value=0, max_value=1000), min_size=1),
    tail=st.floats(min_value=0.0, max_value=0.1),
)
def test_truncated_mean_diff(a, b, tail):
    def compute_truncated_mean(values):
        drop = math.ceil(len(values) * tail)
        values = sorted(values)
        if drop > 0:
            values = values[drop:-drop]
        assume(values)
        return sum(values) / len(values)

    expected = compute_truncated_mean(a) - compute_truncated_mean(b)
    total = len(a) + len(b)
    buf = FFI.new("uint64_t[]", total)
    for i, x in enumerate(a + b):
        buf[i] = x

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, buf, len(a), len(b), 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)
    actual = EXACT.exact_test_truncated_mean_diff(buf, len(a), len(b), tail)
    assert abs(expected - actual) < 1e-8


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    a=u63_lists(min_size=1),
    b=u63_lists(min_size=1),
    quantile=st.floats(min_value=0.0, max_value=0.99),
)
def test_quantile_diff(a, b, quantile):
    def compute_quantile(values):
        values = sorted(values)
        return values[math.floor(quantile * len(values))]

    expected = float(compute_quantile(a) - compute_quantile(b))
    total = len(a) + len(b)
    buf = FFI.new("uint64_t[]", total)
    for i, x in enumerate(a + b):
        buf[i] = x

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, buf, len(a), len(b), 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)
    actual = EXACT.exact_test_quantile_diff(buf, len(a), len(b), quantile)
    assert expected == actual


@hypothesis.settings(deadline=None)
@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    mean_a=st.integers(min_value=1000, max_value=2000),
    sd_a=st.integers(min_value=0, max_value=10),
    mean_b_delta=st.integers(min_value=-100, max_value=-10)
    | st.integers(min_value=10, max_value=100),
    sd_b=st.integers(min_value=0, max_value=10),
)
def test_exact_test_normal_variates(mean_a, sd_a, mean_b_delta, sd_b):
    """Compares two samples generated from different normal distribution.

    The exact_test doesn't have to give us the correct value, but it
    shouldn't (p < 1e-2) be wrong.
    """

    def signum(x):
        if x == 0:
            return 0
        return -1 if x < 0 else 1

    count = 100
    a = [max(0, math.ceil(random.normalvariate(mean_a, sd_a))) for _ in range(count)]
    b = [
        max(0, math.ceil(random.normalvariate(mean_a + mean_b_delta, sd_b)))
        for _ in range(count)
    ]
    statistics = [median("median")]

    # Offset the values enough to flip the order of the centers.
    if mean_b_delta > 0:
        statistics.append(
            median("shifted_median", b_offset=10 + sd_a + sd_b + 2 * abs(mean_b_delta))
        )
    else:
        statistics.append(
            median("shifted_median", a_offset=10 + sd_a + sd_b + 2 * abs(mean_b_delta))
        )

    result = exact_test(a, b, eps=1e-2, statistics=statistics)
    assert result["median"].judgement in (0, signum(-mean_b_delta))
    assert result["shifted_median"].judgement in (0, signum(mean_b_delta))


@pytest.mark.skipif(EXACT is None, reason="exact permutation testing code not loaded")
@given(
    a=st.lists(st.integers(min_value=0, max_value=100), min_size=1),
    b=st.lists(st.integers(min_value=0, max_value=100), min_size=1),
)
def test_actual_data_results(a, b):
    """Computes the median, mean, and lte prob with
    `exact_test._actual_data_results`, and compares with reference
    implementations.
    """

    def compute_q99(values):
        values = sorted(values)
        return values[math.floor(0.99 * len(values))]

    def compute_mean(values):
        return sum(values) / len(values)

    expected_q99 = compute_q99(a) - compute_q99(b)
    expected_mean = compute_mean(a) - compute_mean(b)
    expected_gt = sum(x > y for x in a for y in b) / (len(a) * len(b))

    sample = Sample(a, b)
    plan = [q99("q99", p_a_lower=0.9), mean("mean", a_offset=1), gt_prob("gt")]

    actual = actual_data_results(sample, plan)
    assert actual["q99"] == expected_q99
    assert actual["gt"] == expected_gt
    assert abs(actual["mean"] - expected_mean) < 1e-8
