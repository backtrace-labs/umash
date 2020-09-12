#!/bin/sh
set -e
BASE=$(dirname "$0")

clang-format -i "${BASE}/../"*.[ch] "${BASE}/"*.h "${BASE}/../bench/"*.[ch]
clang-format --style=google -i "${BASE}/../bench/protos/"*.proto
