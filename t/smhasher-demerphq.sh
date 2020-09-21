#!/bin/sh
set -e
BASE=$(dirname $(readlink -f "$0"))

if [ -z "$1" ];
then
    echo "Usage: $0 [path to demerphq SMHasher]";
    exit 1;
fi

TESTS=${2:-All,ReallyAll}

for suffix in 128 64 32 32_hi;
do
    parallel --semaphore --id umash-smhasher -j -1 --fg \
             $1 --test=$TESTS "umash${suffix}" | \
        tee "$BASE/../smhasher/demerphq-umash${suffix}.log" &
done

wait

grep -nHie 'not ok' "$BASE/../smhasher/"demerphq-umash*.log
