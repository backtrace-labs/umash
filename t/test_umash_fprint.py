"""
Test suite for the public fingerprinting function.
"""
from hypothesis import given
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
    multipliers=st.lists(
        st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2
    ),
    key=st.lists(
        # We need 4 more PH values for the Toeplitz shift.
        U64S,
        min_size=C.UMASH_PH_PARAM_COUNT + 4,
        max_size=C.UMASH_PH_PARAM_COUNT + 4,
    ),
    data=st.binary() | repeats(1),
)
def test_public_umash_fprint(seed, multipliers, key, data):
    """Compare umash_fprint with two calls to the reference."""
    expected = [
        umash(UmashKey(poly=multipliers[0], ph=key[:-4]), seed, data),
        umash(UmashKey(poly=multipliers[1], ph=key[4:]), seed, data),
    ]
    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, multiplier in enumerate(multipliers):
        params[0].poly[i][0] = (multiplier ** 2) % FIELD
        params[0].poly[i][1] = multiplier
    for i, param in enumerate(key):
        params[0].ph[i] = param

    actual = C.umash_fprint(params, seed, block, n_bytes)
    assert [actual.hash[0], actual.hash[1]] == expected
