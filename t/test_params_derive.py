"""Minimal test that our parameter derivation logic does what we
expect.
"""
import struct
from hypothesis import given
import hypothesis.strategies as st
from Crypto.Cipher import Salsa20
from umash import C, FFI


@given(
    bits=st.integers(min_value=0, max_value=2 ** 64 - 1),
    key=st.none() | st.binary(min_size=32, max_size=32),
)
def test_public_params_derive(bits, key):
    length = FFI.sizeof("struct umash_params")

    umash_key = b"Do not use UMASH VS adversaries."
    if key is not None:
        umash_key = key
    nonce = struct.pack("<Q", bits)

    expected = FFI.new("struct umash_params[1]")
    salsa_bytes = Salsa20.new(umash_key, nonce).encrypt(b"\x00" * length)
    FFI.memmove(expected, salsa_bytes, length)
    assert C.umash_params_prepare(expected)

    actual = FFI.new("struct umash_params[1]")
    if key is None:
        C.umash_params_derive(actual, bits, FFI.NULL)
    else:
        buf = FFI.new("char[]", len(key))
        FFI.memmove(buf, key, len(key))
        C.umash_params_derive(actual, bits, buf)

    # The values should all be the same.
    assert length % 8 == 0
    for i in range(length // 8):
        assert FFI.cast("uint64_t *", actual)[i] == FFI.cast("uint64_t *", expected)[i]
