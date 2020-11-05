"""
Test suite for the medium (9-16 bytes) input case.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import umash, UmashKey


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)


FIELD = 2 ** 61 - 1


@given(
    seed=U64S,
    multiplier=st.integers(min_value=0, max_value=FIELD - 1),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TOEPLITZ_SHIFT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TOEPLITZ_SHIFT,
    ),
    data=st.binary(min_size=9, max_size=16),
)
def test_umash_medium(seed, multiplier, key, data):
    """Compare umash_medium with the reference."""
    expected = umash(UmashKey(poly=multiplier, oh=key), seed, data, secondary=False)

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2]")
    poly[0] = (multiplier ** 2) % FIELD
    poly[1] = multiplier
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    assert C.umash_medium(poly, params[0].oh, seed, block, n_bytes) == expected
