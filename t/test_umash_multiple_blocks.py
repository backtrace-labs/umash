"""
Test suite for the very long input subroutine.
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


def multiple_blocks_reference(key, initial, seed, data):
    blocks = blockify_chunks(chunk_bytes(data))
    oh_values = oh_compress(key.oh, seed, blocks, secondary=False)
    return poly_reduce(key.poly, len(data), oh_values, initial)


@given(
    initial=U64S,
    seed=U64S,
    multiplier=st.integers(min_value=0, max_value=FIELD - 1),
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
def test_umash_multiple_blocks(initial, seed, multiplier, key, data):
    """Compare umash_multiple_blocks with the reference on short inputs:
    we only invoke `umash_multiple_blocks` on large inputs purely for
    performance reasons.  With respect to pure correctness, it should
    be OK to invoke on any number of integral blocks.
    """
    assert len(data) % 256 == 0
    expected = multiple_blocks_reference(
        UmashKey(poly=multiplier, oh=key), initial, seed, data
    )
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2]")
    poly[0] = (multiplier**2) % FIELD
    poly[1] = multiplier
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    assert (
        C.umash_multiple_blocks(
            initial, poly, params[0].oh, seed, block, n_bytes // 256
        )
        == expected
    )


@given(
    initial=U64S,
    seed=U64S,
    multiplier=st.integers(min_value=0, max_value=FIELD - 1),
    key=st.lists(
        U64S,
        min_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
        max_size=C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT,
    ),
    data=st.lists(repeats(256), min_size=3, max_size=10).map(
        lambda chunks: b"".join(chunks)
    ),
)
def test_umash_multiple_blocks_repeat(initial, seed, multiplier, key, data):
    """Compare umash_multiple_blocks with the reference on longer inputs."""
    assert len(data) % 256 == 0
    expected = multiple_blocks_reference(
        UmashKey(poly=multiplier, oh=key), initial, seed, data
    )
    note(len(data))

    n_bytes = len(data)
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    poly = FFI.new("uint64_t[2]")
    poly[0] = (multiplier**2) % FIELD
    poly[1] = multiplier
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    assert (
        C.umash_multiple_blocks(
            initial, poly, params[0].oh, seed, block, n_bytes // 256
        )
        == expected
    )
