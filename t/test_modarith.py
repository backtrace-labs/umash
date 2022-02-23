"""
Test suite for modular arithmetic, specialised on 2**64 - 8 = 8(2**61 - 1).
"""
import math
from hypothesis import assume, given
import hypothesis.strategies as st
from umash import C, FFI

# We work mod 2**64 - 8.
MODULO = 2**64 - 8

# And the underlying prime field is 2**61 - 1
FIELD = 2**61 - 1

# And assume a 64-bit word size.
W = 2**64


def modint(modulo):
    """The modint strategy generates integer values in [0, modulo)."""
    max_po2 = math.ceil(math.log(modulo, 2))
    # We generate values close to powers of two...
    near_power_of_two = st.builds(
        lambda shift, offset: (1 << shift) + offset,
        st.integers(min_value=0, max_value=max_po2),
        st.integers(min_value=-16, max_value=16),
    )
    # or let Hypothesis do its thing with the whole range
    any_int = st.integers(min_value=0, max_value=modulo - 1)
    # and always reduce the result.
    return (near_power_of_two | any_int).map(lambda x: x % modulo)


@given(x=modint(W), y=modint(MODULO))
def test_add_mod_fast(x, y):
    """Check fast modular addition, for the case we care in practice."""
    assert C.add_mod_fast(x, y) % MODULO == (x + y) % MODULO


@given(x=modint(W), y=modint(W))
def test_add_mod_fast_general(x, y):
    """Exercise the fast modular addition interface's claimed precondition."""
    assume(x + y < 2**65 - 8)
    assert C.add_mod_fast(x, y) % MODULO == (x + y) % MODULO


@given(x=modint(W), y=modint(W))
def test_add_mod_slow(x, y):
    """Make sure the result of `add_mod_slow` is fully reduced."""
    assert C.add_mod_slow(x, y) == (x + y) % MODULO


@given(
    x=st.integers(min_value=W // 2 - 32, max_value=W // 2 + 32),
    y=st.integers(min_value=W // 2 - 32, max_value=W // 2 + 32),
)
def test_add_mod_slow_slow_path(x, y):
    """Exercise the slow path of `add_mod_slow`."""
    assert C.add_mod_slow(x, y) == (x + y) % MODULO


@given(m=modint(FIELD), x=modint(W))
def test_mul_mod_fast(m, x):
    """Check fast modular multiplication, for the case we about."""
    assert C.mul_mod_fast(m, x) % MODULO == (m * x) % MODULO


@given(m=modint(W), x=modint(W))
def test_mul_mod_fast_general(m, x):
    """Check fast modular multiplication, for the case we about."""
    assume(m * x < 2**125)
    assert C.mul_mod_fast(m, x) % MODULO == (m * x) % MODULO


@given(acc=modint(MODULO), m0=modint(FIELD), m1=modint(FIELD), x=modint(W), y=modint(W))
def test_horner_double_update(acc, m0, m1, x, y):
    expected = (m0 * (acc + x) + m1 * y) % MODULO
    assert C.horner_double_update(acc, m0, m1, x, y) == expected


SPLIT_ACCUMULATOR_MAX_FIXUP = 3


@given(
    base=modint(W),
    fixup=st.integers(min_value=0, max_value=SPLIT_ACCUMULATOR_MAX_FIXUP),
)
def test_split_accumulator_eval(base, fixup):
    expected = (base + 8 * fixup) % MODULO
    accumulator = FFI.new("struct split_accumulator[1]")
    accumulator[0].base = base
    accumulator[0].fixup = fixup

    assert C.split_accumulator_eval(accumulator[0]) == expected


@given(
    base=modint(W),
    fixup=st.integers(min_value=0, max_value=SPLIT_ACCUMULATOR_MAX_FIXUP),
    m0=modint(FIELD),
    m1=modint(FIELD),
    h0=modint(W) | st.integers(min_value=2**64 - 5, max_value=2**64 - 1),
    h1=modint(W),
)
def test_split_accumulator_update(base, fixup, m0, m1, h0, h1):
    expected = (m0 * (base + 8 * fixup + h0) + m1 * h1) % MODULO

    accumulator = FFI.new("struct split_accumulator[1]")
    accumulator[0].base = base
    accumulator[0].fixup = fixup

    actual = C.split_accumulator_update(accumulator[0], m0, m1, h0, h1)
    assert 0 <= actual.fixup <= SPLIT_ACCUMULATOR_MAX_FIXUP

    assert C.split_accumulator_eval(actual) == expected
