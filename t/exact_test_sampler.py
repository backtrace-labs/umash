import cffi
from collections import namedtuple
from multiprocessing.pool import Pool
import queue
import os
import secrets
import threading
import time

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


def _generate_in_parallel_worker(generator_fn, generator_args, max_results, max_delay):
    """Toplevel worker for a process pool.  Batches values yielded by
    `generator_fn(*generator_args)` until we have too many values, or
    we hit `max_delay`, and then return that list of values.
    """
    results = []
    end = time.monotonic() + max_delay
    for value in generator_fn(*generator_args):
        results.append(value)
        if len(results) >= max_results or time.monotonic() >= end:
            return results


# At first, return as soon as we have INITIAL_BATCH_SIZE results
INITIAL_BATCH_SIZE = 10
# And let that limit grow up to MAX_BATCH_SIZE
MAX_BATCH_SIZE = 100 * 1000
# Growth rate for the batch size
BATCH_SIZE_GROWTH_FACTOR = 2

# We wait for up to this fraction of the total computation runtime
# before returning values
PROPORTIONAL_DELAY = 0.05

# Wait for at least MIN_DELAY seconds before returning the values we have
MIN_DELAY = 0.01
# And wait for up to MAX_DELAY seconds before returning.
MAX_DELAY = 10

# We lazily create a pool of POOL_SIZE workers.
POOL_SIZE = os.cpu_count() - 1

POOL_LOCK = threading.Lock()
POOL = None


def _get_pool():
    global POOL
    with POOL_LOCK:
        if POOL is None:
            POOL = Pool(POOL_SIZE)
        return POOL


def _generate_in_parallel(generator_fn, generator_args_fn):
    """Merges values yielded by `generator_fn(*generator_args_fn())` in
    arbitrary order.
    """
    # We want multiprocessing to avoid the GIL.  We use relatively
    # coarse-grained futures (instead of a managed queue) to simplify
    # the transition to RPCs.

    # We queue up futures, with up to `max_waiting` not yet running.
    max_waiting = 2
    pending = []

    begin = time.monotonic()
    batch_size = INITIAL_BATCH_SIZE
    pool = _get_pool()

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

    # Adds a new work unit to the pending list.
    def add_work_unit():
        delay = PROPORTIONAL_DELAY * (time.monotonic() - begin)
        if delay < MIN_DELAY:
            delay = MIN_DELAY
        if delay > MAX_DELAY:
            delay = MAX_DELAY
        future_results = pool.apply_async(
            _generate_in_parallel_worker,
            (generator_fn, generator_args_fn(), batch_size, delay),
        )
        pending.append(future_results)

    def fill_pending_list():
        for _ in range(POOL_SIZE + max_waiting):
            # Yeah, we're using internals, but this one hasn't
            # changed since 3.5 (or earlier), and I don't know why
            # this value isn't exposed.
            if pool._taskqueue.qsize() >= max_waiting:
                return
            add_work_unit()

    fill_pending_list()
    while True:
        any_completed = False
        for completed in consume_completed_futures():
            yield completed
            any_completed = True
        if any_completed:
            batch_size = min(BATCH_SIZE_GROWTH_FACTOR * batch_size, MAX_BATCH_SIZE)
            fill_pending_list()


class BufferedIterator:
    """Exposes a queue-like interface for an arbitrary iterator.

    Works by internally spinning up a reader thread.
    """

    BUFFER_SIZE = 4

    def __init__(self, iterator, block_on_exit=True):
        self.iterator = iterator
        self.queue = queue.Queue(self.BUFFER_SIZE)
        self.done = threading.Event()
        self.worker = None
        self.block_on_exit = block_on_exit

    def is_done(self):
        return self.done.is_set() or self.worker is None or not self.worker.is_alive()

    # get and get_nowait may None to denote the end of the iterator.
    def get(self, block=True, timeout=None):
        return self.queue.get(block, timeout)

    def get_nowait(self):
        return self.queue.get_nowait()

    def _pull_from_iterator(self):
        for value in self.iterator:
            if self.done.is_set():
                break
            self.queue.put(value)
            if self.done.is_set():
                break
        # Make sure the reader wakes up.  If the queue is full, the
        # reader should soon grab an item and notice that the queue is
        # done.
        self.done.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

    def __enter__(self):
        self.done.clear()
        self.worker = threading.Thread(target=self._pull_from_iterator)
        self.worker.start()
        return self

    def __exit__(self, *_):
        self.done.set()
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        self.worker.join(None if self.block_on_exit else 0)


def resampled_data_results(sample, grouped_statistics_queue):
    """Yields values computed by the `Statistics` returned by
    `grouped_statistics_queue.get()` after reshuffling values from
    `sample.a_class` and `sample.b_class`.
    """
    cached_stats = [grouped_statistics_queue.get()]

    def grouped_statistics_fn():
        try:
            cached_stats[0] = grouped_statistics_queue.get(block=False)
        except queue.Empty:
            pass
        return cached_stats[0]

    def serial_generator():
        """Calls the generator fn to get new values, while regenerating the
        arguments from time to time.
        """
        current_stats = grouped_statistics_fn()
        while True:
            for value in _resampled_data_results_1(sample, current_stats):
                yield value
                new_stats = grouped_statistics_fn()
                if current_stats is not new_stats:
                    current_stats = new_stats
                    break

    parallel_generator = _generate_in_parallel(
        _resampled_data_results_1, lambda: (sample, grouped_statistics_fn())
    )

    with BufferedIterator(parallel_generator) as buf:
        for value in serial_generator():
            yield value
            try:
                while True:
                    for value in buf.get_nowait():
                        yield value
            except queue.Empty:
                pass
