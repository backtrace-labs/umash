import cffi
from collections import namedtuple
from multiprocessing import Manager
from multiprocessing.pool import Pool
import os
import secrets

from cffi_util import read_stripped_header


SELF_DIR = os.path.dirname(os.path.abspath(__file__))
TOPLEVEL = os.path.abspath(SELF_DIR + "/../") + "/"

FFI = cffi.FFI()

EXACT_HEADERS = ["bench/exact_test.h"]
for header in EXACT_HEADERS:
    FFI.cdef(read_stripped_header(TOPLEVEL + header))

try:
    EXACT = FFI.dlopen(TOPLEVEL + "/exact.so")
except Exception as e:
    print("Failed to load exact.so: %s" % e)
    EXACT = None


Sample = namedtuple("Sample", ["a_class", "b_class"])


# A statistic has a name, and is defined by the preprocessing for the
# data under the null (probability that values from A is lower than
# that from B [likely not quite what one expects], and offsets to add
# to the u63 values for A and B), by the C statistic computation
# function, and by any additional argument for that function.
Statistic = namedtuple(
    "Statistic",
    ["name", "probability_a_lower", "a_offset", "b_offset", "fn_name", "fn_args"],
)


def actual_data_results(sample, statistics):
    """Computes the actual sample value for all `statistics`, for the
    sample values in `sample.a_class` and `sample.b_class`.
    """
    a = sample.a_class
    b = sample.b_class

    def _make_buf():
        buf = FFI.new("uint64_t[]", len(a) + len(b))
        for i, x in enumerate(a + b):
            buf[i] = x
        return buf

    results = dict()
    m = len(a)
    n = len(b)
    buf = _make_buf()
    total = m + n
    copy = FFI.new("uint64_t[]", total)
    FFI.memmove(copy, buf, total * FFI.sizeof("uint64_t"))

    xoshiro = EXACT.exact_test_prng_create()
    EXACT.exact_test_offset_sort(xoshiro, copy, m, n, 0, 0)
    EXACT.exact_test_prng_destroy(xoshiro)

    for stat in statistics:
        value = getattr(EXACT, stat.fn_name)(copy, m, n, *stat.fn_args)
        results[stat.name] = value
    return results


def _resampled_data_results_1(sample, grouped_statistics):
    """Yields values for all the statistics in `grouped_statistics` after
    shuffling values from `sample.a_class` and `sample.b_class`.
    """

    # Reseed to avoid exploring the same random sequence multiple
    # times when multiprocessing.
    EXACT.exact_test_prng_seed(secrets.randbits(64))

    a = sample.a_class
    b = sample.b_class

    def _make_buf():
        buf = FFI.new("uint64_t[]", len(a) + len(b))
        for i, x in enumerate(a + b):
            buf[i] = x
        return buf

    m = len(a)
    n = len(b)
    buf = _make_buf()
    total = m + n
    shuffled_buf = FFI.new("uint64_t[]", total)
    sorted_buf = FFI.new("uint64_t[]", total)
    error_ptr = FFI.new("char**")
    xoshiro = EXACT.exact_test_prng_create()

    def compute_results():
        results = dict()
        for p_a_lt, stats_for_p in grouped_statistics.items():
            FFI.memmove(shuffled_buf, buf, total * FFI.sizeof("uint64_t"))
            if not EXACT.exact_test_shuffle(
                xoshiro, shuffled_buf, m, n, p_a_lt, error_ptr
            ):
                raise "Shuffle failed: %s" % str(FFI.string(error_ptr[0]), "utf-8")

            for (a_offset, b_offset), stats_for_offset in stats_for_p.items():
                FFI.memmove(sorted_buf, shuffled_buf, total * FFI.sizeof("uint64_t"))
                EXACT.exact_test_offset_sort(
                    xoshiro, sorted_buf, m, n, a_offset, b_offset
                )
                for stat in stats_for_offset:
                    results[stat.name] = getattr(EXACT, stat.fn_name)(
                        sorted_buf, m, n, *stat.fn_args
                    )
        return results

    try:
        while True:
            yield compute_results()
    finally:
        EXACT.exact_test_prng_destroy(xoshiro)


def _generate_in_parallel_worker(
    queue,
    generator_fn,
    generator_args,
    initial_batch_size,
    max_batch_size,
    return_after,
):
    """Toplevel worker for a process pool.  Batches values yielded by
    `generator_fn(*generator_args)` and pushes batches to `queue`."""
    batch = []
    # Let the batch size grow linearly to improve responsiveness when
    # we only need a few results to stop the analysis.
    batch_size = initial_batch_size
    total = 0
    for value in generator_fn(*generator_args):
        batch.append(value)
        if len(batch) >= batch_size:
            total += len(batch)
            queue.put(batch)
            if total >= return_after:
                return
            batch = []
            if batch_size < max_batch_size:
                batch_size += 1


def _generate_in_parallel(generator_fn, generator_args_fn, batch_size=None):
    """Merges values yielded by `generator_fn(*generator_args_fn())` in
    arbitrary order.
    """
    ncpu = os.cpu_count()
    # Use a managed queue and multiprocessing to avoid the GIL.
    # Overall, this already seems like a net win at 4 cores, compared
    # to multithreading: we lose some CPU time to IPC and the queue
    # manager process, but less than what we wasted waiting on the GIL
    # (~10-20% on all 4 cores).
    queue = Manager().Queue(maxsize=4 * ncpu)

    # Queue up npu + 2 work units.
    pending = []

    if batch_size is None:
        batch_size = 10 * ncpu

    def generate_values():
        """Calls the generator fn to get new values, while recycling the
        arguments from time to time."""
        while True:
            for i, value in enumerate(generator_fn(*generator_args_fn())):
                if i >= batch_size:
                    break
                yield value

    def get_nowait():
        try:
            return queue.get_nowait()
        except:
            return None

    def consume_completed_futures():
        active = []
        completed = []
        for future in pending:
            if future.ready():
                completed.append(future)
            else:
                active.append(future)
        pending.clear()
        pending.extend(active)
        return [future.get(0) for future in completed]

    with Pool(ncpu - 1) as pool:
        # Adds a new work unit to the pending list.
        def add_work_unit(initial_batch_size=batch_size, return_after=2 * batch_size):
            pending.append(
                pool.apply_async(
                    _generate_in_parallel_worker,
                    (
                        queue,
                        generator_fn,
                        generator_args_fn(),
                        initial_batch_size,
                        batch_size,
                        return_after,
                    ),
                )
            )

        try:
            # Initial work units ramp up.
            for _ in range(ncpu):
                add_work_unit(0)
            for _ in range(2):
                add_work_unit()
            for value in generate_values():
                # Let work units run for longer without communications
                # when we keep going after the initial batch: we're
                # probably in this for the long run.
                for _ in consume_completed_futures():
                    add_work_unit(return_after=5 * batch_size)
                values = [value]
                while values is not None:
                    yield from values
                    values = get_nowait()
        finally:
            pool.terminate()


def resampled_data_results(sample, grouped_statistics_fn):
    """Yields values computed by the Statistics in `grouped_statistics_fn()`
    after reshuffling values from `sample.a_class` and
    `sample.b_class`.
    """
    return _generate_in_parallel(
        _resampled_data_results_1, lambda: (sample, grouped_statistics_fn())
    )
