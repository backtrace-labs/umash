"""
Test suite for the general (16 bytes or longer) input case.
"""
from hypothesis import given, note
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import umash, UmashKey


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)


FIELD = 2 ** 61 - 1


def repeats(min_size):
    """Repeats one byte n times."""
    return st.builds(
        lambda count, binary: binary * count,
        st.integers(min_value=min_size, max_value=1024),
        st.binary(min_size=1, max_size=1),
    )


@given(
    seed=U64S,
    multiplier=st.integers(min_value=0, max_value=FIELD - 1),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=st.binary(min_size=16) | repeats(16),
)
def test_umash_long(seed, multiplier, key, data):
    """Compare umash_long with the reference."""
    expected = umash(UmashKey(poly=multiplier, oh=key), seed, data, secondary=False)
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2]")
    poly[0] = (multiplier ** 2) % FIELD
    poly[1] = multiplier
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    assert C.umash_long(poly, params[0].oh, seed, block, n_bytes) == expected


@given(
    seed=U64S,
    multiplier=st.integers(min_value=0, max_value=FIELD - 1),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=repeats(512),
)
def test_umash_long_repeat(seed, multiplier, key, data):
    """Compare umash_long on repeated strings with the reference."""
    expected = umash(UmashKey(poly=multiplier, oh=key), seed, data, secondary=False)
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2]")
    poly[0] = (multiplier ** 2) % FIELD
    poly[1] = multiplier
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    assert C.umash_long(poly, params[0].oh, seed, block, n_bytes) == expected
