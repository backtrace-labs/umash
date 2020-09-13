#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

if [ -z "$1" ];
then
    echo "Usage: $0 [path to rurban SMHasher]";
    exit 1;
fi

TESTS=${2:-All}

for suffix in 128 64 32 32_hi;
do
    $1 --test=$TESTS "umash${suffix}" | \
        tee "$BASE/../smhasher/umash${suffix}.log";
done

grep -nHie 'fail' "$BASE/../smhasher/"umash*.log
