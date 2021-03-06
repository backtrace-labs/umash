"""
Test suite for OH block compression.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import chunk_bytes, blockify_chunks, oh_compress_one_block


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)

BLOCK_SIZE = 8 * C.UMASH_OH_PARAM_COUNT


def split_block(data):
    """Splits the last (potentially partial) block of 16-byte chunks in data."""
    last_block = []
    for block, _ in blockify_chunks(chunk_bytes(data)):
        last_block = block
    return last_block


@given(
    tag=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_OH_PARAM_COUNT, max_size=C.UMASH_OH_PARAM_COUNT
    ),
    data=st.binary(min_size=BLOCK_SIZE, max_size=BLOCK_SIZE),
)
def test_oh_one_block(tag, key, data):
    """Compare OH compression for full blocks."""
    # The C-side implicit accepts the high half of the tag, and leaves
    # the low half zeroed out.
    expected = oh_compress_one_block(key, split_block(data), tag << 64)

    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", BLOCK_SIZE)
    FFI.memmove(block, data, BLOCK_SIZE)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    actual = C.oh_one_block(params[0].oh, tag, block)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )


@given(
    tag=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_OH_PARAM_COUNT, max_size=C.UMASH_OH_PARAM_COUNT
    ),
    data=st.binary(min_size=16, max_size=BLOCK_SIZE),
)
def test_oh_tail_large(tag, key, data):
    """Compare OH compression for the last block, when it has enough data
    to fully contain the last 16-byte chunk."""
    expected = oh_compress_one_block(key, split_block(data), tag << 64)

    n_bytes = len(data)
    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    actual = C.oh_last_block(params[0].oh, tag, block, n_bytes)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )


@given(
    tag=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_OH_PARAM_COUNT, max_size=C.UMASH_OH_PARAM_COUNT
    ),
    prefix=st.binary(min_size=16, max_size=16),
    data=st.binary(min_size=1, max_size=16),
)
def test_oh_tail_short(tag, key, prefix, data):
    """Compare OH compression for the last block, when we must steal some
    data from the previous chunk."""
    expected = oh_compress_one_block(
        key, split_block(prefix * (C.UMASH_OH_PARAM_COUNT // 2) + data), tag << 64
    )

    offset = len(prefix)
    n_bytes = len(data)
    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", offset + n_bytes)
    FFI.memmove(block, prefix + data, offset + n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].oh[i] = param

    actual = C.oh_last_block(params[0].oh, tag, block + offset, n_bytes)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )
