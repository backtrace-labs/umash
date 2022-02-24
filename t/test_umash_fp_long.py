"""
Test suite for the general (16 bytes or longer) fingerprinting case.
"""
from hypothesis import given, note
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import umash, UmashKey


U64S = st.integers(min_value=0, max_value=2**64 - 1)


FIELD = 2**61 - 1


def repeats(min_size):
    """Repeats one byte n times."""
    return st.builds(
        lambda count, binary: binary * count,
        st.integers(min_value=min_size, max_value=2048),
        st.binary(min_size=1, max_size=1),
    )


@given(
    seed=U64S,
    multipliers=st.lists(
        st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2
    ),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=st.binary(min_size=16) | repeats(16),
)
def test_umash_fp_long(seed, multipliers, key, data):
    """Compare umash_fp_long with the reference."""
    expected = [
        umash(UmashKey(poly=multiplier, oh=key), seed, data, secondary)
        for secondary, multiplier in zip([False, True], multipliers)
    ]
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2][2]")
    for i in range(2):
        poly[i][0] = (multipliers[i] ** 2) % FIELD
        poly[i][1] = multipliers[i]

    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    actual = C.umash_fp_long(poly, params[0].oh, seed, block, n_bytes)
    assert [actual.hash[0], actual.hash[1]] == expected


@given(
    seed=U64S,
    multipliers=st.lists(
        st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2
    ),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=repeats(512),
)
def test_umash_fp_long_repeat(seed, multipliers, key, data):
    """Compare umash_fp_long on repeated strings with the reference."""
    expected = [
        umash(UmashKey(poly=multiplier, oh=key), seed, data, secondary)
        for secondary, multiplier in zip([False, True], multipliers)
    ]
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2][2]")
    for i in range(2):
        poly[i][0] = (multipliers[i] ** 2) % FIELD
        poly[i][1] = multipliers[i]

    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    actual = C.umash_fp_long(poly, params[0].oh, seed, block, n_bytes)
    assert [actual.hash[0], actual.hash[1]] == expected
