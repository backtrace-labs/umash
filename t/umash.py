import cffi
import faulthandler
import os
import re
import sys


SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

# The reference implementation is at the top level.
sys.path.append(TOPLEVEL)

HEADERS = [
    "umash.h",
    "t/umash_test_only.h",
]

FFI = cffi.FFI()


def read_stripped_header(path):
    """Returns the contents of a header file without preprocessor directives."""
    ret = ""
    in_directive = False
    with open(path) as f:
        for line in f:
            if in_directive or re.match(r"^\s*#", line):
                in_directive = line.endswith("\\\n")
            else:
                in_directive = False
                # HACK: ignore the C++ guard
                if line != 'extern "C" {\n' and line != "}\n":
                    ret += line
    return ret


for header in HEADERS:
    FFI.cdef(read_stripped_header(TOPLEVEL + header))

C = FFI.dlopen(os.getenv("UMASH_TEST_LIB", TOPLEVEL + "umash_test_only.so"))

# Pass in a copy of stderr in case anyone plays redirection tricks.
faulthandler.enable(os.dup(2))
