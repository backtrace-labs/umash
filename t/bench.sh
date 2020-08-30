#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

(cd "${BASE}/../";
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall -mpclmul} -DUMASH_TEST_ONLY umash.c \
	   -fPIC --shared -o umash_test_only.so && \
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall} bench/*.c \
	   -fPIC --shared -o bench.so
)

python3 -m venv "${BASE}/umash-venv/"

. "${BASE}/umash-venv/bin/activate"

pip3 install -r "${BASE}/requirements.txt"

black "${BASE}/"*.py

(cd "${BASE}"; UMASH_BENCH_LIB="${BASE}/../bench.so" python3 exact_test.py)
