#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

(cd "${BASE}/../";
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall -mpclmul} umash.c \
	   -fPIC --shared -o libumash.so)

python3 -m venv "${BASE}/umash-venv/"

. "${BASE}/umash-venv/bin/activate"

pip3 install wheel
pip3 install --prefer-binary -r "${BASE}/requirements.txt"

black "${BASE}/"*.py

# Preload ASAN if CFLAGS made us build umash with it.
ASAN_PATH=$(ldd "${BASE}/../libumash.so" | awk '/asan/ { printf(":%s", $3) }')

# We probably don't want to hear about leaks.
if [ -z "$ASAN_OPTIONS" ];
then
    export ASAN_OPTIONS="detect_leaks=0,halt_on_error=0,abort_on_error=1,leak_check_at_exit=0"
fi

cd "${BASE}";
exec env LD_PRELOAD="$LD_PRELOAD:$ASAN_PATH" \
     UMASH_TEST_LIB="${BASE}/../libumash.so" \
     python3 -m pytest -v --forked -n auto -k test_public "$@"
