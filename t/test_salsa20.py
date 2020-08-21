"""
Quick smoke test that our implementation of salsa20 does the right thing.
"""
from hypothesis import given
import hypothesis.strategies as st
from Crypto.Cipher import Salsa20
from umash import C, FFI


@given(
    length=st.integers(min_value=1, max_value=512),
    nonce=st.binary(min_size=8, max_size=8),
    key=st.binary(min_size=32, max_size=32),
)
def test_salsa20(length, nonce, key):
    expected = Salsa20.new(key, nonce).encrypt(b"\x00" * length)
    buf = FFI.new("char[]", length)
    C.salsa20_stream(buf, length, nonce, key)
    assert bytes(FFI.buffer(buf, length)) == expected
