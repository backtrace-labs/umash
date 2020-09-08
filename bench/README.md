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
