"""
Returns a bench runner FFI object for a .so built by t/build-runner.sh.
"""

import cffi
import os
import re
import subprocess
import sys
from types import SimpleNamespace

from cffi_util import read_stripped_header

SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

HEADERS = ["bench/runner.h"]


def load_bench(suffix="WIP"):
    ffi = cffi.FFI()
    for header in HEADERS:
        ffi.cdef(
            read_stripped_header(TOPLEVEL + header, {r"ID\(([^)]+)\)": r"\1_" + suffix})
        )
    path = TOPLEVEL + "umash_bench_runner-" + suffix + ".so"
    print("Loading %s" % path, file=sys.stderr)
    c = ffi.dlopen(path)
    # Strip the suffix from the `c` namespace
    renamed_symbols = SimpleNamespace()
    setattr(renamed_symbols, "__lib", c)
    symbol_suffix = "_" + suffix
    for name in dir(c):
        stripped_name = name
        if stripped_name.endswith(symbol_suffix):
            stripped_name = stripped_name[: -len(symbol_suffix)]
        setattr(renamed_symbols, stripped_name, getattr(c, name))
    return renamed_symbols, ffi, suffix


def build_and_load(commit="WIP", cflags=None):
    env = None
    if cflags is not None:
        current_env = dict(((k, v) for k, v in os.environ.items()))
        current_env["CFLAGS"] = cflags
    result = subprocess.check_output(
        [TOPLEVEL + "t/build-bench-runner.sh", commit], env=env
    )
    print(str(result, "utf-8"))
    match = re.match(rb".* umash_bench_runner-(.*)\.so", result)
    assert match is not None, result
    return load_bench(str(match.group(1), "utf-8"))
