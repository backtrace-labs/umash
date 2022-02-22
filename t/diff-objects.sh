#!/bin/bash

set -e

TARGET=${1:-umash.o}
NEW=${2:-./}
OLD=${3:-/tmp/}

diff --suppress-common-lines -W 180 -y \
     <(objdump --no-show-raw-insn -d "$OLD/$(basename $TARGET)" | \
	   sed -re 's/\.(isra|part)\.[0-9]+//g' -e 's/(__PRETTY_FUNCTION__)0x[0-9a-f]+/\1/g'  -e 's/(\W|^0000)(0x)?[0-9a-f]{4,}\W//g') \
     <(objdump --no-show-raw-insn -d "$NEW/$TARGET" | \
	   sed -re 's/\.(isra|part)\.[0-9]+//g' -e 's/(__PRETTY_FUNCTION__)0x[0-9a-f]+/\1/g'  -e 's/(\W|^0000)(0x)?[0-9a-f]{4,}\W//g')
