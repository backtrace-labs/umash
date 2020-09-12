"""
Decodes umash call traces.
"""

from hashlib import blake2b
import bz2
import os
import re
import shutil
import urllib.request

SELF_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.abspath(SELF_DIR + "/../traces") + "/"

STARTUP_URL = "https://github.com/backtrace-labs/umash/wiki/traces/startup-1M.2020-08-28.trace.bz2"

STARTUP_TAIL_URL = "https://github.com/backtrace-labs/umash/wiki/traces/startup-tail-1M.2020-08-28.trace.bz2"

STEADY_STATE_URL = "https://github.com/backtrace-labs/umash/wiki/traces/steady-state.2020-08-28.trace.bz2"


def _decompress_by_ext(path, ext):
    """Returns a file object for the path; if we recognize the extension,
    decompress the contents."""
    if ext == ".bz2":
        return bz2.open(path, "rb")
    elif ext == "":
        return open(path, "rb")
    else:
        raise Exception("Unknown extension %s" % ext)


def _get_file_contents(url):
    """Returns the (decompressed if possible) contents of the file at url.

    Caches the contents by url under $UMASH_ROOT/traces."""
    url_dir, full_file_name = url.rsplit("/", 1)
    name, ext = os.path.splitext(full_file_name)
    digest = blake2b(bytes(url, "utf-8"), digest_size=16).hexdigest()

    hashed_name = name + "-" + digest + ext
    cache_path = CACHE_DIR + hashed_name
    if not os.path.exists(cache_path):
        try:
            os.mkdir(CACHE_DIR)
        except FileExistsError:
            pass

        with urllib.request.urlopen(url) as response, open(
            cache_path, "wb"
        ) as out_file:
            shutil.copyfileobj(response, out_file)

    return _decompress_by_ext(cache_path, ext)


UMASH_FULL_PATTERN = rb"\s*[^ ]+\s+(\d+).*sdt_libumash:umash_full: \([0-9a-f]+\) arg1=(\d+) arg2=(\d) arg3=(\d+) arg4=(\d+)"


def umash_full_calls(url=STARTUP_URL):
    """Generates tuples describing the "umash_full" calls in the trace at
    `url`.

    The tuples fields are:
    - function ("umash_full")
    - thread id
    - params address
    - `which` argument
    - address of the bytes to hash
    - number of bytes to hash
    """
    with _get_file_contents(url) as f:
        for line in f:
            match = re.match(UMASH_FULL_PATTERN, line)
            if match:
                yield ("umash_full",) + tuple(int(match.group(i)) for i in range(1, 6))
