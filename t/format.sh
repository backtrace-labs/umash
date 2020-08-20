#!/bin/sh
set -e
BASE=$(dirname "$0")

clang-format -i "${BASE}/../"*.[ch] "${BASE}/"*.h
