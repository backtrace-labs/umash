"""Builds and benchmarks multiple versions of UMASH on inputs
generated from traces.
"""
from collections import defaultdict, OrderedDict
import itertools
import random

import bench_loader
import umash_traces


# From https://docs.python.org/3.8/library/itertools.html
def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
    args = [iter(iterable)] * n
    return itertools.zip_longest(*args, fillvalue=fillvalue)


def _full_call_sizes(url, limit=(1 << 64)):
    """Generates the umash_fp sizes < limit (if provided)."""
    thread_traces = defaultdict(list)
    for trace in umash_traces.umash_full_calls(url):
        tid = trace[1]
        size = trace[-1]
        if size < limit:
            thread_traces[tid].append(size)
    return itertools.chain.from_iterable(thread_traces.values())


def _update_results(acc, lengths, timings, count):
    """Groups the parallel arrays of input length and cycle count into `acc`."""
    for i in range(count):
        length = lengths[i]
        acc[length].append(timings[i])


def compare_short_inputs(
    current="WIP",
    baseline="HEAD",
    trace_url=umash_traces.STARTUP_URL,
    length_limit=4,
    cflags=None,
    block_size=128,
    min_count=100000,
    runner="umash_bench_individual",
):
    """Compares the performance of two implementations for short input
    sizes from the input trace.

    If the trace is too short to satisfy `min_count`, retry the experiment
    with shuffled versions of the trace.
    """
    current_lib, ffi, current_suffix = bench_loader.build_and_load(
        current, cflags=cflags
    )
    baseline_lib, _, baseline_suffix = bench_loader.build_and_load(
        baseline, cflags=cflags
    )
    length_arguments = list(_full_call_sizes(trace_url, length_limit))
    max_len = max(length_arguments)

    inputs = ffi.new("size_t[]", block_size)
    timings = ffi.new("uint64_t[]", block_size)

    implementations = [
        (0, getattr(current_lib, runner), defaultdict(list)),
        (1, getattr(baseline_lib, runner), defaultdict(list)),
    ]

    # Don't record results for the first pair of calls: it could
    # suffer from systematic warm-up effects.
    record_results = False
    for _ in range(1 + min_count // len(length_arguments)):
        for block in grouper(length_arguments, block_size):
            random.shuffle(implementations)
            count = len(block)
            for i, value in enumerate(block):
                if value is None:
                    count = i
                    break
                inputs[i] = value

            for _, fn, results in implementations:
                fn(timings, inputs, count, max_len)
                if record_results:
                    _update_results(results, inputs, timings, count)
            record_results = True
        random.shuffle(length_arguments)
    # Undo shuffling, and return the current and baseline values in
    # order.
    implementations.sort()
    return OrderedDict(
        {current_suffix: implementations[0][2], baseline_suffix: implementations[1][2]}
    )
