#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

(cd "${BASE}/../";
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall -mpclmul} -DUMASH_TEST_ONLY umash.c \
	   -fPIC --shared -o umash_test_only.so)

python3 -m venv "${BASE}/umash-venv/"

. "${BASE}/umash-venv/bin/activate"

pip3 install -r "${BASE}/requirements.txt"

black "${BASE}/"*.py

# Preload ASAN if CFLAGS made us build umash with it.
ASAN_PATH=$(ldd "${BASE}/../umash_test_only.so" | awk '/asan/ { printf(":%s", $3) }')

# We probably don't want to hear about leaks.
if [ -z "$ASAN_OPTIONS" ];
then
    export ASAN_OPTIONS="detect_leaks=0,halt_on_error=0,abort_on_error=1,leak_check_at_exit=0"
fi

(cd "${BASE}"; LD_PRELOAD="$LD_PRELOAD:$ASAN_PATH" python3 -m pytest -v --forked -n auto "$@")
