import cffi
import faulthandler
import os
import sys

from cffi_util import read_stripped_header

SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

# The reference implementation is at the top level.
sys.path.append(TOPLEVEL)

HEADERS = [
    "umash.h",
    "t/umash_test_only.h",
]

FFI = cffi.FFI()


for header in HEADERS:
    FFI.cdef(
        read_stripped_header(TOPLEVEL + header, {r'^extern "C" {\n': "", r"}\n": ""})
    )

C = FFI.dlopen(os.getenv("UMASH_TEST_LIB", TOPLEVEL + "umash_test_only.so"))

# Pass in a copy of stderr in case anyone plays redirection tricks.
faulthandler.enable(os.dup(2))
