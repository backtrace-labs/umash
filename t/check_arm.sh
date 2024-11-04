#1/usr/bin/env bash

set -e

cd "$(dirname $0)/.."

NPROC="${1:-1}"
COUNT=1

for CC in clang-15 clang-17 clang-19 gcc gcc-13
do
    for OPT in -O1 -Os -O2 -O3
    do
        for ARCH in "-march=armv8.4-a+crypto" "-march=armv8.4-a+crypto -mtune=native" "-march=native+crypto" "-march=native+crypto -mtune=native"
        do
            for DISPATCH in 0  # no dynamic dispatch on aarch64
            do
                for INLINE_ASM in 0 1
                do
                    for LONG_INPUTS in 0 1
                    do
                        EXE="check-$COUNT"
                        COUNT=$(($COUNT + 1))
                        CMD="$CC $OPT $ARCH -DUMASH_DYNAMIC_DISPATCH=$DISPATCH -DUMASH_INLINE_ASM=$INLINE_ASM -DUMASH_LONG_INPUTS=$LONG_INPUTS"
                        parallel -j $NPROC --semaphore -- "$CMD umash.c example.c -o $EXE && ./$EXE 2>/dev/null | sha256sum --strict --check <(echo '50fff4f41f27a3464445e47bb270c3e027388198aed8734efdba6460d04a3624  -') || echo 'FAILED $CMD'"
                        echo "$(date) $CMD"
                    done
                done
            done
        done
    done
done

parallel --semaphore --wait
