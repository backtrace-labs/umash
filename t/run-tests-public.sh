#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))
PYTHON=${PYTHON3:-python3}

(cd "${BASE}/../";
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall -mpclmul} umash.c \
           '-DUMASH_SECTION="umash_text"' \
	   -fPIC --shared -o libumash.so)

OUT_OF_SECTION_SYMS=$(
    objdump -t "${BASE}/../libumash.so" | grep 'F \.text.*umash' || true
)

# Preload ASAN if CFLAGS made us build umash with it.
ASAN_PATH=$(ldd "${BASE}/../libumash.so" | awk '/asan/ { printf(":%s", $3) }')

# Make sure everything is in the expected section, unless ASan is
# adding its own definitions.
if [ -z "$ASAN_PATH" -a ! -z "$OUT_OF_SECTION_SYMS"  ];
then
    echo "UMASH symbols out of section:\n$OUT_OF_SECTION_SYMS"
    exit 1
fi

$PYTHON -m venv "${BASE}/umash-venv/"

. "${BASE}/umash-venv/bin/activate"

pip3 install wheel
pip3 install --prefer-binary -r "${BASE}/requirements.txt" || \
    pip3 install -r "${BASE}/requirements.txt"

black "${BASE}/"*.py

# We probably don't want to hear about leaks.
if [ -z "$ASAN_OPTIONS" ];
then
    export ASAN_OPTIONS="detect_leaks=0,halt_on_error=0,abort_on_error=1,leak_check_at_exit=0"
fi

cd "${BASE}";
exec env LD_PRELOAD="$LD_PRELOAD:$ASAN_PATH" \
     UMASH_TEST_LIB="${BASE}/../libumash.so" \
     $PYTHON -m pytest -v --forked -n auto -k test_public "$@"
