"""
Test suite for the short (<= 8 bytes) input case.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import vec_to_u64, umash, UmashKey


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)


@given(data=st.binary(min_size=0, max_size=8),)
def test_vec_to_u64(data):
    """Make sure we expand to a uint64 correctly."""
    n_bytes = len(data)
    # Copy to a malloc-ed buffer to help ASan.
    buf = FFI.new("char[]", n_bytes)
    FFI.memmove(buf, data, n_bytes)
    assert C.vec_to_u64(buf, n_bytes) == vec_to_u64(data)


@given(
    seed=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_PH_PARAM_COUNT, max_size=C.UMASH_PH_PARAM_COUNT
    ),
    data=st.binary(min_size=0, max_size=8),
)
def test_umash_short(seed, key, data):
    """Compare umash_short with the reference."""
    expected = umash(UmashKey(poly=0, ph=key), seed, data)

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].ph[i] = param

    assert C.umash_short(params[0].ph, seed, block, n_bytes) == expected
