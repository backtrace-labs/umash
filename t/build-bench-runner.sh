#!/bin/sh

set -e
BASE=$(dirname $(readlink -f "$0"))
COMMIT=${1:-"WIP"}

cd "${BASE}/../";

if [ "x$COMMIT" = "xWIP" ];
then
    echo "Building umash_bench_runner-WIP.so from the current tree.";
    exec ${CC:-cc} ${CFLAGS:- -O2 -std=gnu99 -W -Wall -mpclmul} \
         -DVERSION_SUFFIX="_WIP" -I.  bench/runner.c umash.c \
         -fPIC --shared -o "umash_bench_runner-WIP.so";
fi

SHA=$(git show "$COMMIT" --pretty=format:%H | head -1)
echo "Building umash_bench_runner-$SHA.so"

mkdir -p bench-worktrees;
git worktree add -f "bench-worktrees/$SHA" "$SHA";
cd "bench-worktrees/$SHA";

${CC:-cc} ${CFLAGS:- -O2 -std=gnu99 -W -Wall -mpclmul} \
          -DVERSION_SUFFIX="_$SHA" -I. bench/runner.c umash.c \
          -fPIC --shared -o "../../umash_bench_runner-$SHA.so";

cd ../..;
git worktree remove --force "bench-worktrees/$SHA";
