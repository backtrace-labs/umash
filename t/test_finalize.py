"""
Test suite for the finalizer.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C
from umash_reference import finalize


@given(x=st.integers(min_value=0, max_value=2 ** 64 - 1))
def test_finalize(x):
    assert C.finalize(x) == finalize(x)
