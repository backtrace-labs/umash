"""
Test suite for PH block compression.
"""
from hypothesis import given
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import chunk_bytes, blockify_chunks, ph_compress_one_block


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)

BLOCK_SIZE = 8 * C.UMASH_PH_PARAM_COUNT


def split_block(data):
    """Splits the last (potentially partial) block of 16-byte chunks in data."""
    last_block = []
    for block, _ in blockify_chunks(chunk_bytes(data)):
        last_block = block
    return last_block


@given(
    seed=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_PH_PARAM_COUNT, max_size=C.UMASH_PH_PARAM_COUNT
    ),
    data=st.binary(min_size=BLOCK_SIZE, max_size=BLOCK_SIZE),
)
def test_ph_one_block(seed, key, data):
    """Compare PH compression for full blocks."""
    expected = ph_compress_one_block(key, seed, split_block(data))

    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", BLOCK_SIZE)
    FFI.memmove(block, data, BLOCK_SIZE)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].ph[i] = param

    actual = C.ph_one_block(params[0].ph, seed, block)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )


@given(
    seed=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_PH_PARAM_COUNT, max_size=C.UMASH_PH_PARAM_COUNT
    ),
    data=st.binary(min_size=16, max_size=BLOCK_SIZE),
)
def test_ph_tail_large(seed, key, data):
    """Compare PH compression for the last block, when it has enough data
    to fully contain the last 16-byte chunk."""
    expected = ph_compress_one_block(key, seed, split_block(data))

    n_bytes = len(data)
    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", n_bytes)
    FFI.memmove(block, data, n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].ph[i] = param

    actual = C.ph_last_block(params[0].ph, seed, block, n_bytes)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )


@given(
    seed=U64S,
    key=st.lists(
        U64S, min_size=C.UMASH_PH_PARAM_COUNT, max_size=C.UMASH_PH_PARAM_COUNT
    ),
    prefix=st.binary(min_size=16, max_size=16),
    data=st.binary(min_size=1, max_size=16),
)
def test_ph_tail_short(seed, key, prefix, data):
    """Compare PH compression for the last block, when we must steal some
    data from the previous chunk."""
    expected = ph_compress_one_block(
        key, seed, split_block(prefix * (C.UMASH_PH_PARAM_COUNT // 2) + data)
    )

    offset = len(prefix)
    n_bytes = len(data)
    # Copy to exactly-sized malloced buffers to help ASan.
    block = FFI.new("char[]", offset + n_bytes)
    FFI.memmove(block, prefix + data, offset + n_bytes)
    params = FFI.new("struct umash_params[1]")
    for i, param in enumerate(key):
        params[0].ph[i] = param

    actual = C.ph_last_block(params[0].ph, seed, block + offset, n_bytes)
    assert expected == actual.bits[0] + (actual.bits[1] << 64), (
        actual.bits[0],
        actual.bits[1],
    )
