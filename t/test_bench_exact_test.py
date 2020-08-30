"""
Test the exact statistical testing code (its internals, mostly).
"""
import pytest
from hypothesis import given
import hypothesis.strategies as st
from umash import BENCH
from umash import BENCH_FFI as FFI


def u63_lists():
    def make_list(length, min_value, max_value, random):
        min_value, max_value = sorted((min_value, max_value))
        return [random.randint(min_value, max_value) for _ in range(length)]

    long_lists = st.builds(
        make_list,
        st.integers(min_value=10, max_value=1000),
        st.integers(min_value=0, max_value=10000),
        st.integers(min_value=0, max_value=10000),
        st.randoms(use_true_random=True),
    )
    dense_lists = st.builds(
        make_list,
        st.integers(min_value=10, max_value=1000),
        st.just(10),
        st.just(12),
        st.randoms(use_true_random=True),
    )
    sparse_lists = st.builds(
        make_list,
        st.integers(min_value=10, max_value=1000),
        st.just(0),
        st.just(2 ** 63 - 1),
        st.randoms(use_true_random=True),
    )
    return (
        st.lists(st.integers(min_value=0, max_value=2 ** 63 - 1))
        | long_lists
        | dense_lists
        | sparse_lists
    )


@pytest.mark.skipif(BENCH is None, reason="benchmarking code not loaded")
@given(values=u63_lists())
def test_offset_sort(values):
    xoshiro = BENCH.exact_test_prng_create()
    expected = sorted([2 * x for x in values])
    buf = FFI.new("uint64_t[]", len(values))
    for i, x in enumerate(values):
        buf[i] = x
    # Sort `len(values)` sampled values from A, and none from B.
    # That's the same as sorting the values shifted left by 1 bit.
    BENCH.exact_test_offset_sort(xoshiro, buf, len(values), 0, 0, 0)
    BENCH.exact_test_prng_destroy(xoshiro)

    actual = [buf[i] for i in range(len(values))]
    assert expected == actual
