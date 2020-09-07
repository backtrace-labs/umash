"""
Test the exact statistical testing code (its internals, mostly).
"""
import math
import pytest
import random
import hypothesis
from hypothesis import given
import hypothesis.strategies as st
from exact_test import EXACT, FFI, exact_test, median


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
