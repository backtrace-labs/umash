#!/bin/sh
set -e

BASE=$(dirname $(readlink -f "$0"))
cd "$BASE/.."
exec git clean -fix -e .sampler_servers.ini
