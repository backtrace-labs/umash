Exact testing that knows when to stop
=====================================

Parametric tests are a bad fit for computer performance data, where
the distributions are often multimodal and heavily skewed.
Non-parametric tests can be used safely on such data, but often need a
lot more measurements than parametric approaches, and don't let us ask
as rich a set a questions as parametric tests.

In the past, I've used [the Confidence Sequence Method](https://pvk.ca/Blog/2018/07/06/testing-slo-type-properties-with-the-confidence-sequence-method/)
and [similar sequential](https://github.com/pkhuong/one-sided-ks)
[testing methods](https://github.com/pkhuong/martingale-cs)
to compare cycle count distributions with
[Sign tests](https://en.wikipedia.org/wiki/Sign_test),
[Kolmogorov-Smirnov tests](https://en.wikipedia.org/wiki/Kolmogorov%E2%80%93Smirnov_test),
and by [computing credible intervals for quantiles](https://github.com/pkhuong/csm/blob/8a14ba444343c07e97a2de24d2048b2edcc7cbb7/csm.h#L54).

However, each test tends to require bespoke logic, and, as we add more
tests to our gauntlet, we need more data, in order to
[compensate for multiple comparisons](https://en.wikipedia.org/wiki/Bonferroni_correction).

Performance testing is an interesting case of analysing
computer-generated data.  It's usually easy to just burn more cycles
in order to get more data points... but it doesn't work that way for
performance testing, which must often be run on one of a few
standardised and well-isolated machines.

[Exact permutation testing](https://en.wikipedia.org/wiki/Resampling_(statistics)#Permutation_tests)
offers us another option in the design space: we can measure a
reasonably sized data set on our performance testing machines, come up
with an arbitrary statistic (e.g., the difference in sample average
value between implementations A and B), and use computing power
*on any number of machines* to resample from the data set and see how
likely it would be to observe a statistic value as extreme as we did,
if the values for the two implementations were sampled from the same
underlying distribution.

For example, we could generate two sets of one million observations:

    A = [max(0, math.ceil(random.normalvariate(10000, 1000))) for _ in range(1000000)]
    B = [max(0, math.ceil(random.normalvariate(10001, 1000))) for _ in range(1000000)]

    sum(A) / len(A)  # 10000.141788
    sum(B) / len(B)  # 10003.09523

and (pretending we don't know the underlying distributions), observe
that the sample average for set `A` is 2.95 less than that for set
`B`.  We now want to know if that's due to chance, or if we can
reasonably conclude that the distribution average for `A` is less than
that for `B`.

We can't actually answer that with a permutation test (or in general,
since the mean is so sensitive to outliers that it may not always be
finite or even defined).  However, we can estimate the probability
that we observe a statistic as extreme (`mean(A) - mean(B) <= -2.95`
or `mean(A) - mean(B) >= -2.95`) if the two data sets were generated
from the same underlying distribution.  For example, if we randomly
relabeled the data 100 times to yield `A'` and `B'` and found that
`mean(A') - mean(B') > -2.95` all 100 times, we could roughly estimate
that the probability of observing a different as negative as -2.95
would be less than 1% if the underlying distributions were the same.

Given this data, one might reasonably decide to infer that the
distribution average of `A` is less than that of `B`.  There are still
two problems with this method, and we'll only be able to fix one.

The first, more fundamental, issue is that we haven't actually
excluded the middle, even in probability.  We observed a difference in
sample mean, and want to know if that's real, or could just be a
random fluke, while the actual difference in distribution means is zero,
or even of the opposite sign.  When a permutation test rejects the
null hypothesis, however, it doesn't tell us that the difference is
probably real: since the null hypothesis is that the distribution that
underlies our two sample is the same, a rejection only tells us that
the distributions are probably different.

In our sample mean example, we could imagine that sample `A` was
actually generated from a distribution that usually samples from the
`N(10000, 1000)` normal distribution, but sometimes, with probability
`1e-20`, yields `1e100`.  The average for this distribution is close
to `1e80`, much higher than 10000, but there's pretty much no chance
of us distinguishing that distribution from `N(10000, 1000)` with a
reasonable (significantly smaller than `1e20`) sample size.  That's
just the way things are when we try to answer questions that don't
exactly match non-parametric tests (applying parametric tests when the
data's distribution doesn't match the tests' preconditions is also not
great).

In practice, we can ask whether there's value in trying to consider
events that happen with probability much smaller than `1/sample_size`,
when we can sample millions of data points.  I would probably start by
worrying about differences between the performance testing and
production environments, and whether my two samples were actually
generated under similar enough environments.

The other issue with the Monte Carlo is that it's not obvious when to
stop.  Let's say we executed 100 iteration of the resampling method,
and never observed a value less than or equal to -2.95.  We can
roughly estimate that, were the underlying distributions for A and B
identical, we would observe -2.95 or worse with probability around
`1/102`.  However, that's only an almost-unbiased estimator, and not a
confidence bound.  We can also compute a
[Binomial credible interval](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval),
and bound the probability that we would observe -2.95 or worse with
identical underlying distributions.  That's would actually be correct
for p-value usage... but still doesn't help us know when to stop.

We can't simply compute a proportion interval at every iteration:
without correcting for the higher number of repeated tests, that would
be [p-hacking](https://en.wikipedia.org/wiki/Data_dredging).
Thankfully, we find ourselves back in a Binomial or quantile
estimation problem, and can use simple sequential binomial tests, like
the [Confidence Sequence Method](https://github.com/pkhuong/csm).  A
sequential test will let us generate more and more data from the null
hypothesis with Monte Carlo resampling, and tell us when we have
enough data to give an answer, without inflating the error rate above
the target `epsilon`.

Let's rephrase the question we're now trying to answer more
formally.  We have a data set in which each point is labeled with a
class A or B, and we computed a statistic on that sample (e.g.,
difference of the sample means for classes A and B).  We now want to
know if that statistic's value is useful signal, or could be a
somewhat probable fluke.

That's a hard question, especially once we replace the
difference-of-sample-means function with an arbitrary black box, so
we'll instead ask something subtly different.  We have a labeled data
set `X`, and found the actual statistic value `a = f(X)`.  We will
determine whether a value as extreme as `a` would be unlikely if there
was no association between the label and the rest of the data (e.g.,
cycle counts), i.e., if the labels might as well have been assigned
randomly.

This scenario, the labels were assigned randomly or are otherwise
completely independent of the data, is our null hypothesis.  We'll set
a false positive rate `epsilon`, e.g., `epsilon = 0.001`, and our job
is to provide an algorithm that will erroneously reject the null
(i.e., claim the underlying distributions for the two classes are
different when the labels were actually assigned randomly) with
probability at most `epsilon`.  We'll do so by estimating whether `a =
f(x)`, our sample statistic, is either less than the `epsilon/2`th
quantile, or the `1 - epsilon/2`th quantile, for the distribution
of that same statistic, with random labels (i.e., for the null hypothesis).

That's the same as determining whether less than `epsilon/2` of
randomly labeled data sets (with otherwise the same values as the real
observations) yield `f(x') <= a`, or whether less than `epsilon/2` of
the same randomly labeled data sets yield `f(x') >= a`.  If either of
these things are true, we can conclude that a value as extreme as `a`
happens with probability at most `epsilon` under the null, and reject
the null hypothesis with error rate `epsilon`.

If the null doesn't hold (labels are meaningful, i.e., associated with
different distributions for the measured data), we're by definition
never wrong, since it's not an error to fail to reject the null
hypothesis... which also means there is no guarantee that, e.g., the
sign of the sample statistic matches that of the distribution
statistic, even when we reject the null.  In fact, our pathological
example of an almost-normal distribution that very rarely yields a
huge value shows that it's impossible to provide such a guarantee in
general.  In practice, insert some more hand waving here about how a
value extreme enough to reject the null hypothesis is probably extreme
enough to assume it points in the right direction.

If the null holds, we only reject for a set of labels (those that
yield `f(x)` in the bottom or top `epsilon/2`th quantile) that are
generated with probability `epsilon`; our rejection rate when labels
are generated randomly is at most `epsilon`, and that's exactly what
we promised.

When we use sequential binomial testing (or any statistical test) to
compare `a` against our estimate of the distribution quantiles from
the Monte Carlo resamplings, we must also take into account the error
rate of the binomial test itself.  The amount of Monte Carlo
repetitions needed for a test scales inverse quadratically with the
quantile itself (i.e., scales with `1/epsilon^2`), and only
logarithmically with the binomial test's allowed error rate.  That's
why we use an asymmetric split: for a total error rate `epsilon`, we
compute quantiles at `epsilon / (2 * 1.1) = epsilon / 2.2` with
internal error rate `epsilon / 22`.

At first sight, this p-value mode of thinking offers answers to
questions that no one cares about.  However, we can show that
tejecting the null hypothesis is sort of relevant with an informal
Bayesian argument.  Let's say we start with an estimate that there's a
10% chance that classes A and B aren't assigned randomly, and that the
difference between the two classes is in fact wide enough that we will
correctly reject the null hypothesis at least 50% of the time (these
are all just "gut feeling" estimates).  If we parameterise our
test to reject the null hypothesis with `epsilon <= 0.001` (0.1%),
we can estimate that the probability that we reject the null and
the class labels are assigned randomly is at most
`0.1 * 0.5 / (0.1 * 0.5 + 0.9 * 0.001) = 0.982`.  Assuming our
gut is a superforecaster, we can look at data for which we rejected
the null hypothesis, and claim a 98.2% chance that the labels aren't
random (and are in fact non-random in a way that our statistic can
detect).  There's a lot of hand-waving in this estimate, but it
shows how a low `epsilon` value lets us infer that we detected
a meaningful difference.

TL;DR
-----

You build a data set labeled with two classes, and computed a
statistic on that data set (e.g., difference of sample means).  You
now want to know if that statistic is representative of the underlying
distributions.

Wouldn't we all!

What's actually on offer here is an algorithm that, once combined with
your arbitrary statistic function and the process that generated the
data set, becomes a Monte Carlo algorithm to determine whether the
labels are somehow correlated or associated with the sample's
measurements.

Set an arbitrary error rate `epsilon`.  When the labels are
independent of the measurements, we will tell you that's the case (not
reject the null hypothesis) with probability at least `1 - epsilon`,
for any statistic function.  When the labels are associated with the
measurements, we don't guarantee anything.  However, if we reject the
null hypothesis, you can do some hand wavey Bayesian thinking to see
if you want to believe that the sample statistic is useful signal.

We will also do that with a sequential testing algorithm and thus
always eventually gives you an answer (unless you managed to get a
sample for which the statistic is exactly equal to one of the `epsilon
/ 2.2` quantiles), while needing fewer ierations for easy cases.

In practice, this means we will usually determine that we don't reject
the null hypothesis quickly (in which case you may either conclude
nothing, or decide to try again with more data), and reject the null
eventually, but slowly, after `O^~(1 / epsilon^2)` iterations.

I want to use this for continuous performance regression testing!
-----------------------------------------------------------------

Automated regression testing is always harder, especially when
statistics are involved.  One option is to set the sample size
by estimating the
[power](https://en.wikipedia.org/wiki/Power_of_a_test)
for a few key scenarios (e.g., with a shifed mean).  Given a powerful
enough test, we can essentially accept the null: when we (quickly)
determine that the sample doesn't let us reject the null hypothesis,
we can conclude that any difference between the distributions of data
for the two labels is probably smaller than that the scenarios we used
to set the sample size.

Realistically, any effect that needs more than millions of data points
to detect is probably negligible in practice.... but we might still
want positive confirmation of the absence of a regression.

We can also set an upper bound on the acceptable regression (e.g., we
could decide to ignore any difference that ends up shifting the
distribution of cycle counts up by at most 5 cycles).  As long as we
keep comparing against multiple historical builds, this should keep
any drift in check, while only flagging regressions large enough to
look into.

That's something we can set up as our null hypothesis for exact
permutation testing.  Let's say we're still comparing the sample
means, and now want to know if the difference in sample means between
classes A and B, -2.95, is too extreme to observe even if the two
classes were sampled from different distributions, where the
distribution for B is the same as A, but shifted up by 5 (i.e., where
we expect a difference in sample means of -5).  We can do that by
incrementing all values in class B after a random re-labeling.  We
should slowly (after more than `1 / epsilon^2` iterations) find that
a difference of -2.95 is smaller than expected, and thus reject the
null which, in this case, means that the difference in the sample
means probably isn't associated with a *large enough* (at least 5
cycles per call) regression.

Serious people don't track average performance
----------------------------------------------

I would rephrase that to "don't *only* track average performance."  I
think everyone eventually cares about throughput and average
latencies.  However, we also want to pay attention to other metrics,
like high percentiles, or more complex domain specific metrics (e.g.,
missed deadlines weighted by transaction value, or the difference between
two estimated parameters in a regression).

In some other cases (e.g., when evaluating a proposed code change that
purpots to improve performance), we might want to estimate what
percentage of the time the new code performs better than the old code
(with inputs that have been partitioned finely enough that runtimes
may be assumed i.i.d.), and vice versa.

These are all values we can estimate with a deterministic statistic
function, from a sample.  The permutation test code can then help us
determine if the output of that deterministic function for the data we
observed seems too extreme to believe that the old and new code
actually behave identically (with respect to that statistic).
