#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

(cd "${BASE}/../bench/";
 ${CC:-cc} ${CFLAGS:- -O2 -std=c99 -W -Wall} xoshiro.c exact_test.c \
	   -fPIC --shared -o ../exact.so
)

python3 -m venv "${BASE}/umash-venv/"

. "${BASE}/umash-venv/bin/activate"

pip3 install wheel
pip3 install --prefer-binary -r "${BASE}/requirements.txt"
pip3 install --prefer-binary -r "${BASE}/requirements-bench.txt"

black "${BASE}/"*.py

cd "${BASE}/../bench/notebooks"
exec env PYTHONPATH="$BASE:$PYTHONPATH" jupyter notebook
