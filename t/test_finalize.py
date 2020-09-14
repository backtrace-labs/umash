"""
Test suite for the finalizer.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C
from umash_reference import finalize, rotl


@given(x=st.integers(min_value=0, max_value=2 ** 64 - 1))
def test_finalize(x):
    assert C.finalize(x) == finalize(x)


def xor_rot2_inv(x, a=8, b=33):
    """We can invert xoring 2 rotations by exponentiating the
    corresponding bit matrix."""
    for _ in range(6):  # Square log_2(64) = 6 times.
        x = x ^ rotl(x, a) ^ rotl(x, b)
        a = (2 * a) % 64
        b = (2 * b) % 64
    return x


@given(x=st.integers(min_value=0, max_value=2 ** 64 - 1))
def test_finalize_inverse(x):
    """Confirm that the finalizer is invertible, by composing it with
    its purported inverse function."""
    finalized = finalize(x)
    assert xor_rot2_inv(finalized) == x


def test_finalize_inverse_basis():
    """The finalizer is linear (and thus, so is its inverse).  Check that
    we can invert a simple basis for the 64-bit vector space: the set of
    64-bit integers with exactly one bit set.
    """
    assert finalize(0) == 0, "The finalizer is expected to be linear."
    assert xor_rot2_inv(0) == 0, "The unfinalizer is expected to be linear."
    for i in range(64):
        x = 1 << i

        finalized = finalize(x)
        assert xor_rot2_inv(finalized) == x

        unfinalized = xor_rot2_inv(x)
        assert x == finalize(unfinalized)
