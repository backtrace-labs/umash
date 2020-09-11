import attr
import cffi
from collections import defaultdict, namedtuple
from multiprocessing.pool import Pool
import pickle
import queue
import os
import secrets
import threading
import time

from cffi_util import read_stripped_header

# Don't force a dependency on gRPC just for testing.
try:
    from exact_test_sampler_pb2 import AnalysisRequest, ResultSet
    from exact_test_sampler_pb2_grpc import ExactTestSamplerServicer
except:
    print("Defaulting dummy gRPC/proto definitions in exact_test_sampler.py")

    @attr.s
    class RawData:
        a_values = attr.ib(factory=list)
        b_values = attr.ib(factory=list)

    @attr.s
    class AnalysisRequest:
        raw_data = attr.ib(factory=RawData)
        parameters = attr.ib(factory=bytes)

    @attr.s
    class ResultSet:
        @attr.s
        class StatisticValues:
            name = attr.ib(factory=str)
            values = attr.ib(factory=list)

        results = attr.ib(factory=list)

        def SerializeToString(self):
            """We don't really serialise."""
            return self

        def ParseFromString(self, value):
            self.results = value.results

    class ExactTestSamplerServicer:
        pass


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


def _convert_result_arrays_to_proto(dict_of_arrays):
    ret = ResultSet()
    for name, values in dict_of_arrays.items():
        proto = ResultSet.StatisticValues()
        proto.statistic_name = name
        proto.values[:] = values
        ret.results.append(proto)
    return ret


def _convert_proto_to_result_dicts(result_set):
    max_length = max(len(stats.values) for stats in result_set.results)
    dicts = [dict() for _ in range(max_length)]

    for stats in result_set.results:
        name = stats.statistic_name
        for i, value in enumerate(stats.values):
            dicts[i][name] = value
    return dicts


def _generate_in_parallel_worker(generator_fn, generator_args, max_results, max_delay):
    """Toplevel worker for a process pool.  Batches values yielded by
    `generator_fn(*generator_args)` until we have too many values, or
    we hit `max_delay`, and then return that list of values, converted
    to a ResultSet.
    """
    results = defaultdict(list)
    end = time.monotonic() + max_delay
    for i, value in enumerate(generator_fn(*generator_args)):
        for k, v in value.items():
            results[k].append(v)
        if i >= max_results or time.monotonic() >= end:
            return _convert_result_arrays_to_proto(results)


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
MIN_DELAY = 0.05
# And wait for up to MAX_DELAY seconds before returning.
MAX_DELAY = 10

# We lazily create a pool of POOL_SIZE workers.
POOL_SIZE = max(1, os.cpu_count() - 1)

POOL_LOCK = threading.Lock()
POOL = None

# Backoff parameters when polling for updates in _generate_in_parallel.
POLL_PROPORTIONAL_DELAY = 0.5
POLL_MIN_DELAY = 0.01
POLL_MAX_DELAY = 1.0


def _get_pool():
    global POOL
    with POOL_LOCK:
        if POOL is None:
            POOL = Pool(POOL_SIZE)
        return POOL


def _generate_in_parallel(generator_fn, generator_args_fn, stop_event=None):
    """Yields values returned by parallel calls to
    `generator_fn(*generator_args_fn())` in arbitrary order.

    If `stop_event` is provided, returns when `stop_event.is_set()`.
    """
    # We want multiprocessing to avoid the GIL.  We use relatively
    # coarse-grained futures (instead of a managed queue) to simplify
    # the transition to RPCs.

    if stop_event is None:
        stop_event = threading.Event()

    # We queue up futures, with up to `max_waiting` not yet running.
    max_waiting = 2
    pending = []

    begin = time.monotonic()
    batch_size = INITIAL_BATCH_SIZE
    pool = _get_pool()

    def backoff(last_change):
        elapsed = time.monotonic() - last_change
        delay = POLL_PROPORTIONAL_DELAY * elapsed
        if delay < POLL_MIN_DELAY:
            delay = POLL_MIN_DELAY
        if delay > POLL_MAX_DELAY:
            delay = POLL_MAX_DELAY
        stop_event.wait(delay)

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
        any_change = False
        for _ in range(POOL_SIZE + max_waiting):
            # Yeah, we're using internals, but this one hasn't
            # changed since 3.5 (or earlier), and I don't know why
            # this value isn't exposed.
            if pool._taskqueue.qsize() >= max_waiting:
                break
            add_work_unit()
            any_change = True
        return any_change

    fill_pending_list()
    last_activity = begin
    while not stop_event.is_set():
        any_completed = False
        for completed in consume_completed_futures():
            yield completed
            any_completed = True
        if any_completed:
            batch_size = min(BATCH_SIZE_GROWTH_FACTOR * batch_size, MAX_BATCH_SIZE)
        any_change = fill_pending_list()
        if any_completed or any_change:
            last_activity = time.monotonic()
        else:
            backoff(last_activity)


@attr.s
class ExactTestParameters:
    # Signaled when the request should be exited
    done = attr.ib(factory=threading.Event)
    # Signaled when sample and params are both populated
    ready = attr.ib(factory=threading.Event)
    lock = attr.ib(factory=threading.Lock)
    sample = attr.ib(default=None)
    params = attr.ib(default=None)


class ExactTestSampler(ExactTestSamplerServicer):
    # How long to wait for a_values, b_values, and params.
    INITIAL_DATA_TIMEOUT = 60

    @staticmethod
    def _update_test_params(params, update_requests, ctx):
        for analysis_request in update_requests:
            if ctx and not ctx.is_active():
                break
            with params.lock:
                if (
                    analysis_request.raw_data.a_values
                    or analysis_request.raw_data.b_values
                ):
                    params.sample = Sample(
                        a_class=list(analysis_request.raw_data.a_values),
                        b_class=list(analysis_request.raw_data.b_values),
                    )

                if analysis_request.parameters:
                    params.params = pickle.loads(analysis_request.parameters)

                if params.sample is not None and params.params is not None:
                    params.ready.set()
        params.done.set()

    def simulate(self, requests, ctx):
        """Requests is an iterator of AnalysisRequest.  This method yields
        arrays of analysis values, and is not yet a full-blown Servicer
        implementation.
        """
        params = ExactTestParameters()
        updater = None

        def read_params():
            with params.lock:
                return (params.sample, params.params)

        try:
            updater = threading.Thread(
                target=self._update_test_params,
                args=(params, requests, ctx),
                daemon=True,
            )
            updater.start()

            params.ready.wait(timeout=self.INITIAL_DATA_TIMEOUT)
            for value in _generate_in_parallel(
                _resampled_data_results_1, read_params, params.done
            ):
                if params.done.is_set():
                    break
                yield value
                if params.done.is_set():
                    break
        finally:
            params.done.set()
            if updater is not None and updater.is_alive():
                updater.join(0.001)


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
    request_queue = queue.SimpleQueue()
    cached_stats = [None]

    def grouped_statistics_fn(block=False):
        try:
            cached_stats[0] = grouped_statistics_queue.get(block=block)
            req = AnalysisRequest()
            req.parameters = pickle.dumps(cached_stats[0])
            request_queue.put(req)
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

    try:
        sampler = ExactTestSampler()
        initial_req = AnalysisRequest()
        initial_req.raw_data.a_values[:] = sample.a_class
        initial_req.raw_data.b_values[:] = sample.b_class
        request_queue.put(initial_req)
        # Make sure we have an initial value for the analysis parameers.
        grouped_statistics_fn(block=True)

        parallel_generator = sampler.simulate(iter(request_queue.get, None), None)
        with BufferedIterator(parallel_generator) as buf:
            for value in serial_generator():
                yield value
                try:
                    while True:
                        for value in _convert_proto_to_result_dicts(buf.get_nowait()):
                            yield value
                except queue.Empty:
                    pass
    finally:
        # Mark the end of the request iterator.
        request_queue.put(None)
