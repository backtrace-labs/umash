How to use UMASH's benchmarking support
=======================================

Really quick start
-----------------

1. Execute `t/bench.sh`

2. Open one of the [jupytext](https://github.com/mwouts/jupytext) notebooks
   under `bench/notebooks` in Jupyter.

3. The default settings compare the current tree, the `TEST`
   implementation, with the `BASELINE` implementation in `HEAD`.
   Overwrite these global variables to other commit hashes to
   compare `umash` at these commits.

4. (Re-)run the whole notebook from scratch, and a wait a bit.

The result should be all self-explanatory (lower is beter), except for
the last cell, which performs a set of significance tests on a few
statistics that compare the `TEST` and `BASELINE` implementations,
for each input size.

The "mean" entry computes the difference between the truncated mean
latency for `TEST` and `BASELINE`, with the most extreme 0.5% data
points removed at each end.  Negative is good means the test code
is on average faster than the baseline.

A results like

    'mean': Result(actual_value=-2.4834334334334334, judgement=-1, m=20000, n=20000, num_trials=2000000)

reports that the test code was on average 2.48 cycles faster than the
baseline, during our benchmarking loop.  The `judgement` tells us if
this difference is statistically significant: -1 means the value is
low enough that it's unlikely to happen if the two implementations had
the same latency distribution, 1 means the value is similarly
improbably high if the two implementations had the same latency, and 0
means we don't know.

In the case of the truncated mean, `judgement=-1` is a good thing,
while 1 is bad news for the TEST version.

The "lte" entry computes the probability that a randomly chosen value
from the TEST latencies is less than or equal to a randomly chosen
value from the BASELINE latencies.  If we assume that the variability
is all due to (i.i.d.) noise, this is the same as asking what
percentage of the time it would be better to use the test version than
the baseline.  A higher `actual_value` (more than 0.5) is better, and
we want `judgement=1`.

The "q99" entry computes the difference between the two distributions'
99th percentile.  As with the truncated mean, more negative is better,
and we want `judgement=-1`.

Quantile distributions can be surprisingly flat when comparing cycle
counts: values are quantised, and we can expect a lot of duplicates.
This can make it hard to find signal.  We also compute "q99\_sa" which
compares the sample difference of 99th percentiles with a shifted
version of the null hypothesis: we now suppose that the two
implementations have the same distribution latency, except that the
test implementation is shifted to be 5 cycles slower than the
baseline.  If we find `judgement=1` for "q99\_sa", the difference in
99th percentiles is so positive, that it's improbably high even for
that pessimistic null hypothesis; we can probably conclude that the
test version has made the 99th percentile worse.

Speed up the analysis
---------------------

The bulk of the time in the notebooks will be spent not generating
benchmarking data, but analysing it to determine whether the reported
statistic values (e.g., different in means) are statistically
significant.  This can take a surprising amount of time, on the order
of 1 CPU hours per input size on my 1.1 GHz Kaby Lake laptop.
Thankfully, this Monte Carlo step is also embarrassingly parallel, and
there's already gRPC wrappers for the computational core.

Set up servers by cloning the UMASH repository on each compute server,
and executing `t/exact_test_server.sh $PORT`.  This will spin up a
compute server that listens on `localhost:$PORT` for work units.  You
may also leave the port argument blank (`t/exact_test_server.sh`) to
let the server pick a listening port.  The server always prints the
listening port on success.

The server only accepts connections from localhost because it does not
implement authentication or permissioning.  Use something like an
[ssh tunnel](https://help.ubuntu.com/community/SSH/OpenSSH/PortForwarding)
to expose the port to analysis machines.

We can now go back to the analysis machine, open ssh tunnels to each
`exact_test_server`, and edit (create) a `.sampler_servers.ini` in
the UMASH directory.  For each server, add an entry like

    [compute_server_1]  # name of the connection
    hostname = localhost
    port = 9000

It's not a big deal if you get the format or information wrong.  We
re-parse that configuration file for every call to
`exact_test.exact_test`, so there's no need to restart a notebook's
kernel; simply edit the configuration file and rerun the step.

With or without distributed analysis, it also makes sense to tune
down the `eps` (false result rate) argument during development.  I
would use `eps=1e-3` or `eps=1e-2` for rapid feedback, and re-run from
scratch with `eps=1e-4` once things look ready for a pull request.

What does it do?
----------------

The first step in benchmarking is to come up with interesting inputs.

We have UMASH call
[traces from a production-ish workload](https://github.com/backtrace-labs/umash/wiki/Execution-traces)
on the wiki, and use those as our source of representative calls.
I doubt there is any real pattern in the sequence of input sizes,
but the relative frequency of hashed data sizes is useful.

The code in `t/umash_traces.py` handles downloading traces, caching
them locally, and parsing the output of `perf script`.

The `# List the distribution of input sizes in the trace.` cell in
`bench_tiny_inputs.md` calls `umash_traces.umash_full_calls` to
iterate over the calls in the "startup" trace, and summarise the
distribution of short input sizes.  We can see that 1-byte calls are
extremely rare for us, 2-byte only slightly more frequent.

    [(1, 7),
     (2, 51),
     (3, 396),
     (4, 1312),
     (5, 3110),
     (6, 5616),
...

For tiny (< 4 bytes) inputs, we'll want to extract calls into UMASH
for fewer than 4 bytes, and use measure the latency on synthetical
invocation with that distribution of input sizes.

Now that we have call traces, we can run interesting benchmarks.

That happens in the
`# Gather the raw data for the two revisions we want to compare`
cell, where

    results = umash_bench.compare_short_inputs(current=TEST,
                                               baseline=BASELINE,
                                               length_limit=4,
                                               min_count=1000000)

builds `umash.c` for the current and baseline versions, loads both
resulting shared objects in the Python process, and calls the
wrappers defined in `bench/runner.h` on batches of test inputs.

For more details on the building and loading process, read
`t/bench_loader.py` and `t/build-bench-runner.sh`.  We use the
preprocessor to give unique names to the external entry points we need
(the benchmarking loops in `bench/runner.c`), and use `objcopy` to
hide all other symbols to avoid collision.

The actual benchmarking happens in `t/umash_bench.py`:
`umash_short_inputs` calls into `bench_loader` to obtain cffi bindings
into the two benchmarking libraries, derives arrays of length
arguments from the trace data, and passes the same arrays to the each
benchmarking libraries.  That function returns the results re-grouped
by input size in a pair of dicts, for the test and baseline versions.
In theory, we could use that to perform paired tests, but we will
focus on unpaired statistics, because we would prefer to assume that
the distribution of call latency is a function of the input size, and
otherwise noise.

All that's left is regular data analysis.

The first step in data analysis should always be to visualise the data.
We do that with [plotly express](https://github.com/plotly/plotly.py):
for each input size, we plot the distribution of latencies for the two
implementations.  We truncate the x axis to in order to be able to see
something, so we also compute how much data that leaves out.

Having taken a look at the data, we probably have some gut feeling on
the relative performance of the two implementation.  However, it's
good to back that with something stronger and reproducible, like
statistical tests.  The last cell computes a few summary statistics to
compare the performance of the two implementations (difference of
truncated mean, probability that a test call is faster than a baseline
call, and difference of 99th percentiles), and, more importantly,
determines whether each value is statistically significant, with an
exact permutation test.

That last bit can treacherous be hard to understand; see
EXACT_TESTS.md for more information.
