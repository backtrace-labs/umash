import cffi
import os

from cffi_util import read_stripped_header


SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

EXACT_HEADERS = ["bench/exact_test.h"]

FFI = cffi.FFI()


for header in EXACT_HEADERS:
    FFI.cdef(read_stripped_header(TOPLEVEL + header))

try:
    EXACT = FFI.dlopen(TOPLEVEL + "/exact.so")
except Exception as e:
    print("Failed to load exact.so: %s" % e)
    EXACT = None
