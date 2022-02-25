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


def _full_call_sizes(url, min=0, limit=(1 << 64), length_fixup=None):
    """Generates the umash_fp sizes < limit (if provided)."""
    if length_fixup is None:
        length_fixup = 0
    thread_traces = defaultdict(list)
    for trace in umash_traces.umash_full_calls(url):
        tid = trace[1]
        size = trace[-1] + length_fixup
        if min <= size < limit:
            thread_traces[tid].append(size)
    return itertools.chain.from_iterable(thread_traces.values())


def _update_results(acc, lengths, timings, count):
    """Groups the parallel arrays of input length and cycle count into `acc`."""
    for i in range(count):
        length = lengths[i]
        acc[length].append(timings[i])


def compare_inputs(
    length_arguments,
    current="WIP",
    baseline="HEAD",
    cflags=None,
    cc=None,
    block_size=128,
    min_count=100000,
    runner="umash_bench_individual",
    options={},
):
    """Compares the performance of two implementations for input sizes in `length_arguments`.

    If that list is too short to satisfy `min_count`, retry the experiment
    with shuffled versions of the list.
    """

    def try_index(x, i):
        """Returns x[i] if x is a list or a tuple, and x otherwise.

        This is equivalent to broadcasting `x` to a repeated list
        when it's an atom.
        """
        if isinstance(x, list) or isinstance(x, tuple):
            return x[i]
        else:
            return x

    current_lib, ffi, current_suffix = bench_loader.build_and_load(
        current,
        cflags=try_index(cflags, 0),
        cc=try_index(cc, 0),
    )
    baseline_lib, baseline_ffi, baseline_suffix = bench_loader.build_and_load(
        baseline,
        cflags=try_index(cflags, 1),
        cc=try_index(cc, 1),
    )
    max_len = max(length_arguments)

    inputs = ffi.new("size_t[]", block_size)
    timings = ffi.new("uint64_t[]", block_size)

    def make_options(target_ffi):
        ret = target_ffi.new("struct bench_individual_options *")
        ret.size = target_ffi.sizeof("struct bench_individual_options")
        for field, value in options.items():
            setattr(ret, field, value)
        return ret

    implementations = [
        (0, getattr(current_lib, runner), make_options(ffi), defaultdict(list)),
        (
            1,
            getattr(baseline_lib, runner),
            make_options(baseline_ffi),
            defaultdict(list),
        ),
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

            for _, fn, options, results in implementations:
                fn(options, timings, inputs, count, max_len)
                if record_results:
                    _update_results(results, inputs, timings, count)
            record_results = True
        random.shuffle(length_arguments)
    # Undo shuffling, and return the current and baseline values in
    # order.
    implementations.sort()
    return OrderedDict(
        {current_suffix: implementations[0][3], baseline_suffix: implementations[1][3]}
    )


def compare_short_inputs(
    current="WIP",
    baseline="HEAD",
    trace_url=umash_traces.STARTUP_URL,
    length_limit=4,
    length_fixup=None,
    cflags=None,
    cc=None,
    block_size=128,
    min_count=100000,
    runner="umash_bench_individual",
    options={},
):
    """Compares the performance of two implementations for short input
    sizes from the input trace.

    If the trace is too short to satisfy `min_count`, retry the experiment
    with shuffled versions of the trace.

    Tracing may reveal suboptimal integration, e.g., where a program
    includes the NUL terminator in the hash.  Set length_fixup=-1
    to subtract 1 from the length of each call.
    """
    length_arguments = list(_full_call_sizes(trace_url, 0, length_limit, length_fixup))

    return compare_inputs(
        length_arguments,
        current,
        baseline,
        cflags,
        cc,
        block_size,
        min_count,
        runner,
        options,
    )


def compare_long_inputs(
    current="WIP",
    baseline="HEAD",
    trace_url=umash_traces.STARTUP_URL,
    length_min=16,
    length_fixup=None,
    cflags=None,
    cc=None,
    block_size=128,
    min_count=100000,
    runner="umash_bench_individual",
    options={},
):
    """Compares the performance of two implementations for long input
    sizes from the input trace.

    If the trace is too short to satisfy `min_count`, retry the experiment
    with shuffled versions of the trace.

    Tracing may reveal suboptimal integration, e.g., where a program
    includes the NUL terminator in the hash.  Set length_fixup=-1
    to subtract 1 from the length of each call.
    """
    length_arguments = list(
        _full_call_sizes(trace_url, length_min, 1 << 64, length_fixup)
    )

    return compare_inputs(
        length_arguments,
        current,
        baseline,
        cflags,
        cc,
        block_size,
        min_count,
        runner,
        options,
    )
