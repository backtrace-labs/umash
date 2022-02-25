"""
Test suite for the very long input fingerprinting subroutine.
"""
from hypothesis import given, note
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import (
    blockify_chunks,
    chunk_bytes,
    oh_compress,
    poly_reduce,
    UmashKey,
)


U64S = st.integers(min_value=0, max_value=2**64 - 1)


FIELD = 2**61 - 1


def repeats(size):
    """Repeats one byte exactly size times."""
    return st.binary(min_size=1, max_size=1).map(lambda binary: binary * size)


def multiple_blocks_reference(keys, initials, seed, data):
    def ref(key, initial, secondary):
        blocks = blockify_chunks(chunk_bytes(data))
        oh_values = oh_compress(key.oh, seed, blocks, secondary)
        return poly_reduce(key.poly, len(data), oh_values, initial)

    return [
        ref(key, initial, secondary)
        for key, initial, secondary in zip(keys, initials, [False, True])
    ]


@given(
    initials=st.lists(U64S, min_size=2, max_size=2),
    seed=U64S,
    multipliers=st.lists(
        st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2
    ),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=repeats(256)
    | repeats(512)
    | st.binary(min_size=256, max_size=256)
    | st.binary(min_size=512, max_size=512),
)
def test_umash_fprint_multiple_blocks(initials, seed, multipliers, key, data):
    """Compare umash_fprint_multiple_blocks with the reference on short
    inputs: we only invoke `umash_fprint_multiple_blocks` on large
    inputs purely for performance reasons.  With respect to pure
    correctness, it should be OK to invoke on any number of integral
    blocks.
    """
    assert len(data) % 256 == 0
    expected = multiple_blocks_reference(
        [UmashKey(poly=multipliers[0], oh=key), UmashKey(poly=multipliers[1], oh=key)],
        initials,
        seed,
        data,
    )
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    mul = FFI.new("uint64_t[2][2]")
    for i in range(2):
        mul[i][0] = (multipliers[i] ** 2) % FIELD
        mul[i][1] = multipliers[i]

    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    poly = FFI.new("struct umash_fp[1]")
    poly[0].hash[0] = initials[0]
    poly[0].hash[1] = initials[1]

    actual = C.umash_fprint_multiple_blocks(
        poly[0], mul, params[0].oh, seed, block, n_bytes // 256
    )
    generic = C.umash_fprint_multiple_blocks_generic(
        poly[0], mul, params[0].oh, seed, block, n_bytes // 256
    )

    assert (
        [actual.hash[0], actual.hash[1]]
        == [generic.hash[0], generic.hash[1]]
        == expected
    )


@given(
    initials=st.lists(U64S, min_size=2, max_size=2),
    seed=U64S,
    multipliers=st.lists(
        st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2
    ),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=st.lists(repeats(256), min_size=3, max_size=10).map(
        lambda chunks: b"".join(chunks)
    ),
)
def test_umash_fprint_multiple_blocks_repeat(initials, seed, multipliers, key, data):
    """Compare umash_fprint_multiple_blocks with the reference on longer
    inputs."""
    assert len(data) % 256 == 0
    expected = multiple_blocks_reference(
        [UmashKey(poly=multipliers[0], oh=key), UmashKey(poly=multipliers[1], oh=key)],
        initials,
        seed,
        data,
    )
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    mul = FFI.new("uint64_t[2][2]")
    for i in range(2):
        mul[i][0] = (multipliers[i] ** 2) % FIELD
        mul[i][1] = multipliers[i]

    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    poly = FFI.new("struct umash_fp[1]")
    poly[0].hash[0] = initials[0]
    poly[0].hash[1] = initials[1]

    actual = C.umash_fprint_multiple_blocks(
        poly[0], mul, params[0].oh, seed, block, n_bytes // 256
    )
    generic = C.umash_fprint_multiple_blocks_generic(
        poly[0], mul, params[0].oh, seed, block, n_bytes // 256
    )

    assert (
        [actual.hash[0], actual.hash[1]]
        == [generic.hash[0], generic.hash[1]]
        == expected
    )
