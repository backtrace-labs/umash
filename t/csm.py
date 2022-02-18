"""A safely rounded implementation of Ding, Gandy, and Hahn's
Confidence Sequence Method for dynamic termination of Binomial tests
on Monte Carlo simulations (https://arxiv.org/abs/1611.01675), coupled
with code to compute Bayesian credible intervals on the underlying
success rate.

This code is distributed under the BSD license and the Apache License
version 2.0 (http://www.apache.org/licenses/LICENSE-2.0).  See the end
of the file for details.
"""
import math
import random
import struct
from typing import cast, IO, Iterable, Iterator, Optional, Tuple


__all__ = ["csm", "beta_icdf", "csm_driver", "csm_power"]


# Float frobbing utilities.  Increment/decrement floats by a few ULPs
# to direct rounding.


def float_bits(x: float) -> int:
    """Convert float to sign-magnitude bits, then to 2's complement.

    >>> float_bits(0.0)
    0
    >>> float_bits(-0.0)
    -1
    >>> float_bits(1.0)
    4607182418800017408
    >>> float_bits(-2.5)
    -4612811918334230529
    >>> -float_bits(math.pi) - 1 == float_bits(-math.pi)
    True
    >>> float_bits(1.0) > 0
    True
    >>> float_bits(-1.0) < 0
    True
    """
    bits = struct.unpack("=q", struct.pack("=d", x))[0]
    significand = cast(int, bits % (1 << 63))
    # ~significand = -1 - significand. We need that instead of just
    # -significand to handle signed zeros.
    return significand if bits >= 0 else ~significand


def bits_float(bits: int) -> float:
    """Convert 2's complement integer to sign-magnitude bits, then float.

    >>> bits_float(0)
    0.0
    >>> bits_float(-1)
    -0.0
    >>> bits_float(4607182418800017408)
    1.0
    >>> bits_float(-4612811918334230529)
    -2.5
    >>> bits_float(4607182418800017409)
    1.0000000000000002
    >>> bits_float(float_bits(1.0))
    1.0
    >>> bits_float(float_bits(-math.pi)) == -math.pi
    True
    """
    if bits < 0:
        significand = bits % (1 << 63)
        bits = ~significand
    result = struct.unpack("=d", struct.pack("=q", bits))[0]
    return cast(float, result)


def next(x: float, delta: int = 1) -> float:
    """Increment x by delta ULPs.

    >>> next(-0.0)
    0.0
    >>> next(-0.0, 2) > 0.0
    True
    >>> next(0.0)
    5e-324
    >>> next(-0.0, 2)
    5e-324
    >>> next(1.0)
    1.0000000000000002
    >>> next(-1.0)
    -0.9999999999999999
    >>> -1.0 < next(-1.0) < next(-1.0, 2) < -1.0 + 1e-15
    True
    >>> 0 < next(0.0) < next(0.0, 2) < 1e-15
    True
    >>> 1.0 < next(1.0) < next(1.0, 2) < 1 + 1e-15
    True
    >>> math.pi == next(math.pi, 0)
    True
    >>> next(-math.pi, 2) == next(next(-math.pi))
    True
    """
    return bits_float(float_bits(x) + delta)


def prev(x: float, delta: int = 1) -> float:
    """Decrement x by delta ULPs.

    >>> prev(0.0)
    -0.0
    >>> prev(0.0, 2) < -0.0
    True
    >>> prev(-0.0)
    -5e-324
    >>> prev(1.0)
    0.9999999999999999
    >>> prev(-1.0)
    -1.0000000000000002
    >>> -1.0 > prev(-1.0) > prev(-1.0, 2) > -1.0 - 1e15
    True
    >>> -0.0 > prev(-0.0) > prev(-0.0, 2) > -1e-15
    True
    >>> 1.0 > prev(1.0) > prev(1.0, 2) > 1 - 1e-15
    True
    >>> math.pi == prev(math.pi, 0)
    True
    >>> prev(-math.pi, 2) == prev(prev(-math.pi))
    True
    """
    return bits_float(float_bits(x) - delta)


# Wrap log/log1p for one-sided errors.

LIBM_ERROR_LIMIT = 4  # Assume libm is off by less than 4 ULPs.


def log_up(x: float) -> float:
    """Conservative upper bound on log(x).

    >>> 0.0 < log_up(1.0) < 1e-10
    True
    >>> 0 < log_up(1e-10) - math.log(1e-10) < 5e-13
    True
    >>> 0 < log_up(4) - math.log(4) < 1e-10
    True
    >>> log_up(1.0)
    2e-323
    >>> log_up(0.1)
    -2.3025850929940437
    >>> log_up(20.0)
    2.9957322735539926
    """
    return next(math.log(x), LIBM_ERROR_LIMIT)


def log_down(x: float) -> float:
    """Conservative lower bound on log(x).

    >>> -1e-10 < log_down(1.0) < 0.0
    True
    >>> -5e-13 < log_down(1e-10) - math.log(1e-10) < 0
    True
    >>> -1e-10 < log_down(4) - math.log(4) < 0
    True
    >>> log_down(1.0)
    -1.5e-323
    >>> log_down(0.1)
    -2.3025850929940472
    >>> log_down(20.0)
    2.995732273553989
    """
    return prev(math.log(x), LIBM_ERROR_LIMIT)


def log1p_up(x: float) -> float:
    """Conservative upper bound on log(1 + x).

    >>> 0.0 < log1p_up(0.0) < 1e-16
    True
    >>> 0.0 < log1p_up(-1e-10) - math.log1p(-1e-10) < 1e-20
    True
    >>> 0.0 < log1p_up(0.5) - math.log1p(0.5) < 1e-10
    True
    >>> log1p_up(0.0)
    2e-323
    >>> log1p_up(-0.1)
    -0.10536051565782625
    >>> log1p_up(1e-4)
    9.99950003333084e-05
    """
    return next(math.log1p(x), LIBM_ERROR_LIMIT)


def log1p_down(x: float) -> float:
    """Conservative lower bound on log(1 + x).

    >>> -1e-16 < log1p_down(0.0) < 0.0
    True
    >>> -1e-20 < log1p_down(-1e-10) - math.log1p(-1e-10) < 0.0
    True
    >>> -1e-10 < log1p_down(0.5) - math.log1p(0.5) < 0.0
    True
    >>> log1p_down(0.0)
    -1.5e-323
    >>> log1p_down(-0.1)
    -0.10536051565782636
    >>> log1p_down(1e-4)
    9.999500033330829e-05
    """
    return prev(math.log1p(x), LIBM_ERROR_LIMIT)


# Kahan-style summation.
#
# Represent the accumulator as an evaluated sum of two doubles.  As
# long as the compensation term is initially 0, the result is a safe
# upper bound on the real value, and the two terms are
# "non-overlapping."  For more details, see "Adaptive Precision
# Floating-Point Arithmetic and Fast Robust Geometric Predicates",
# Shewchuk, 1997; Technical report CMU-CS-96-140R / Discrete & Comp
# Geom 18(3), October 1997.  Theorem 6 in particular.


def sum_update_up(accumulator: Tuple[float, float], term: float) -> Tuple[float, float]:
    """Increment the accumulator (value, error) pair by term.

    Given accumulator = (acc, compensation), an unevaluated sum
      acc + compensation,
    return a new unevaluated sum for an upper bound of
      acc + compensation + term.

    >>> sum_update_up((1.0, 0.0), 0.5)
    (1.5, 0.0)
    >>> sum_update_up((3.0, 1e-16), math.pi)
    (6.141592653589793, 4.440892098500626e-16)
    >>> sum_update_up((10e10, 1e-8), math.pi * 1e-10)
    (100000000000.0, 1.0314159265358981e-08)
    >>> sum_update_up((math.pi * 1e-10, 1e-8), 10e10)
    (100000000000.0, 1.0314159265358981e-08)
    """
    acc, compensation = accumulator
    if abs(acc) < abs(term):
        acc, term = term, acc
    shifted = next(term + compensation)
    if compensation <= 0:
        term = min(term, shifted)
    else:
        term = shifted
    # Dekker sum of accumulator + term.  The result is exact,
    # do we don't need next/prev here.
    #
    # |acc| >= |term|
    a, b = acc, term
    x = a + b
    b_virtual = x - a
    y = b - b_virtual
    return (x, y)


def sum_update_finish(accumulator: Tuple[float, float]) -> Tuple[float, float]:
    """Compute an upper bound for the unevaluated sum in accumulator.

    Normalise accumulator so that the compensation term is negative.
    The first value is then an upper bound on the real value of the
    accumulator, which is itself an upper bound on the exact sum of
    the terms passes to sum_update_up.

    >>> sum_update_finish((6.141592653589793, 4.440892098500626e-16))
    (6.141592653589794, -4.440892098500626e-16)
    >>> sum_update_finish((100000000000.0, -1.0314159265358981e-08))
    (100000000000.0, -1.0314159265358981e-08)
    >>> sum_update_finish((1e16, 1.0))
    (1.0000000000000002e+16, -1.0)
    """
    acc, compensation = accumulator
    if compensation > 0:
        bound = next(acc + compensation)
    else:
        # compensation <= 0; acc is already an upper bound.
        bound = min(acc, next(acc + compensation))
    delta = bound - acc
    assert delta >= compensation
    return (bound, compensation - delta)


def sum_up(*values: float) -> float:
    """Conservative upper bound with Kahan/Dekker-style error compensation.

    Conservative upper bound for the sum of values, via the one-sided
    Kahan summation loop above.

    >>> sum_up(1.0, -2.0, 3.0, -4.0)
    -2.0
    >>> sum_up(2.5, 1e16, -1e16)
    4.0
    >>> sum_up(1.0, 0.5, 0.25, 1.0 / 8) + 1.0 / 8
    2.0
    """
    accumulator = 0.0, 0.0
    for value in values:
        accumulator = sum_update_up(accumulator, value)
    return sum_update_finish(accumulator)[0]


# Upper bound for log c(n, s)
#
# Use Robbins's "A Remark on Stirling's Formula," The American
# Mathematical Monthly, Vol 62, No 1 (Jan 1955), pp 26-29.
# http://www.jstor.org/stable/2308012.
#
#
# \sqrt{2\pi} n^{n + 1/2} exp[-n + 1/(12n + 1)]
# < n! <
# \sqrt{2\pi} n^{n + 1/2} exp[-n + 1/(12n)]
#
# to upper bound log c(n, s) = log(n!) - log(s!) - log((n - s)!).


# Smallest double precision value > - log sqrt(2 pi)
MINUS_LOG_SQRT_2PI = -8277062471433908.0 * (2**-53)


def robbins_log_choose(n: int, s: int) -> float:
    """Over-approximate log c(n, s).

    Compute a conservative upper bound on log c(n, s), based on
    Robbins's bounds for k!.

    >>> robbins_log_choose(5, 5)
    0.0
    >>> robbins_log_choose(1, 0)
    0.0
    >>> 10 < math.exp(robbins_log_choose(10, 9)) < 10 + 1e-10
    True
    >>> 20 < math.exp(robbins_log_choose(20, 1)) < 20 + 1e-10
    True
    >>> 0 < robbins_log_choose(10, 5) \
          - math.log((10 * 9 * 8 * 7 * 6) / (5 * 4 * 3 * 2)) < 1e-2
    True
    >>> robbins_log_choose(4, 2)
    1.7944835223684492
    >>> robbins_log_choose(10000, 100)
    556.7980123668373
    >>> robbins_log_choose(10000, 8000)
    4999.416373646588
    """
    assert 0 < n < 1 << 49
    assert 0 <= s <= n
    # Handle easy cases, where c(n, s) is 1 or n.
    if s == 0 or s == n:
        return 0.0
    if s == 1 or s == n - 1:
        return log_up(n)
    n_s = n - s
    l1 = next((n + 0.5) * log_up(n))
    l2 = next(-(s + 0.5) * log_down(s))
    l3 = next(-(n_s + 0.5) * log_down(n_s))
    r1 = next(1.0 / (12 * n))
    r2 = next(-1.0 / (12 * s + 1))
    r3 = next(-1.0 / (12 * n_s + 1))
    return sum_up(MINUS_LOG_SQRT_2PI, l1, l2, l3, r1, r2, r3)


# Confidence Sequence Method.
#
# See "A simple method for implementing Monte Carlo tests,"
# Ding, Gandy, and Hahn, 2017 (https://arxiv.org/abs/1611.01675).
#
# Correctness is a direct corollary of Robbins's "Statistical
# Methods Related to the Law of the Iterated Logarithm" (Robbins,
# Ann. Math. Statist. Vol 41, No 5 (1970), pp 1397-1409.
# https://projecteuclid.org/euclid.aoms/1177696786.
#
# Let { x_i : i \in |N } be a sequence of i.i.d. Bernoulli random
# variables with success probability 0 < P(x_i = 1) = p < 1, for
# all i.
#
# Further let S_n = \sum_{i=1}^n x_i, i.e., the number of successes
# in the first n terms, and b(n, p, s) = c(n, s) p^s (1 - p)^{n - s}.
#
# The probability of any n > 0 satisfying
#    b(n, p, S_n) < eps / (n + 1)),
# for 0 < eps < 1, is less than eps.
#
# We can thus check whether the inequality above is ever satisfied,
# and, when it is, decide that the stream of Bernoullis observed has
# P(x_i = 1) != p.
#
# Ding, Gandy, and Hahn show that we can also expect the empirical
# success rate S_n/n to be on the same side of the threshold p (alpha
# in this implementation) as the real but unknown success rate
# of the i.i.d. Bernoullis.


def csm(n: int, alpha: float, s: int, log_eps: float) -> Tuple[bool, float]:
    """CSM test for n trials, p != alpha, s successes, epsilon = exp(log_eps).

    Given n trials and s sucesses, are we reasonably sure that the
    success rate is *not* alpha (with a false positive rate less than
    exp(log-eps)?

    Answer that question with Ding, Gandy, and Hahn's confidence
    sequence method (CSM). The second return value is an estimate of
    the false positive target rate we would need to stop here.  This
    value should only be used for reporting; the target rate eps
    should always be fixed before starting the experiment.

    >>> csm (1, 0.5, 1, -1)
    (False, 9.992007221626409e-16)
    >>> csm (1, 0.5, 0, -1)
    (False, 9.992007221626409e-16)
    >>> csm(100, 0.9, 98, math.log(1e-5))[0]
    False
    >>> csm(100, 0.9, 98, math.log(0.2))[0]
    True
    >>> csm(int(1e9), 0.99, int(0.99 * 1e9), -1e-2)[0]
    False
    >>> csm(10000, 0.01, 50, math.log(1e-9))[0]
    False
    >>> csm(10000, 0.01, 50, math.log(1e-3))[0]
    True
    >>> csm(10, 0.05, 1, -10.0)
    (False, 1.243108442750477)
    >>> csm(100000, 0.05, 100, -10.0)
    (True, -4624.756745998)
    >>> csm(1000000, 0.99, 990596, -10.0)
    (False, -9.977077184266818)
    >>> csm(1000000, 0.99, 990597, -10.0)
    (True, -10.039129993485403)
    """
    assert 0 < n < 1 << 49
    assert 0 < alpha < 1
    assert 0 <= s <= n
    assert log_eps < 0
    log_level = sum_up(
        log_up(n + 1),
        robbins_log_choose(n, s),
        next(s * log_up(alpha)),
        next((n - s) * log1p_up(-alpha)),
    )
    return log_level < log_eps, log_level


# Beta confidence intervals.
#
# Approximate the CDF of the Beta(a, b), the regularised incomplete
# Beta function I_x(a, b) with an upper bound based on the
# hypergeometric representation
#
#   I_x(a, b) = [Gamma(a + b)/(Gamma(a) Gamma(b)) x^a (1 - x)^b/a] * \
#               sum_s=0^\infty [(a + b)_s / (a + 1)_s] x^s,
# where
#   (a + b)_0 = 1,
#   (a + b)_1 = 1 * (a + b) = a + b
#   (a + b)_s = 1 * (a + b) * (a + b + 1) * ... * (a + b + s - 1)
# and, similarly for (a + 1)_s,
#   (a + 1)_0 = 1,
#   (a + 1)_1 = 1 * (a + 1) = a + 1,
#   (a + 1)_s = 1 * (a + 1) * (a + 2) * ... * (a + s).
#
# The summands [(a + b)_s / (a + 1)_s] x^s can thus be reformulated
# as
#  \pi_s(a, b, x) := [(a + b)_s / (a + 1)_s] x^s
#                 = \prod_i=1^s [(a + b - 1 + i) / (a + i)]x
#                 = \prod_i=1^s [1 + (b - 1) / (a + i)]x.
#
# The parameters a and b are positive integers, so we can also
# compute
#   Gamma(a + b)/(Gamma(a) Gamma(b)) x^a (1 - x)^b/a
# as
#   c(a + b - 1, a) x^a (1 - x)^b.
#
# This is a product of very small and very large terms, so we'll
# work on log space for that initial value.  Once it's computed, the
# summands monotonically approach 0 from above, so we can use normal
# arithmetic.  We can also easily overapproximate every intermediate
# value, starting with Robbins's approximation for
# log(c(n, s)) = log(c(a + b - 1, a)).
#
# This series of products representation lets us compute upper and
# lower bounds for the tail of a partial sum, by over- and under-
# approximating the tail with geometric series
#   \pi_s(a, b, x) \sum_j=1^\infty x^j
#  < \sum_j=1^\infty \pi_{s + j}(a, b, c) <
#   \pi_s(a, b, x) \sum_j=1^\infty \pi_s(a, b, x)^j
#
# and thus
#
#   \pi_s(a, b, x) [1 / (1 - x) - 1]
#  < \sum_j=1^\infty \pi_{s + j}(a, b, c) <
#   \pi_s(a, b, x) [1 / (1 - \pi_s(a, b, x)) - 1].
#
# Given conservative comparisons between threshold and the limits for
# our one-sided over-approximation of I_x(a, b), we can execute a
# bisection search and invert the over-approximation.  The result is a
# conservative lower bound for the confidence interval on the actual
# Beta CDF I_x(a, b).


def _incbeta(
    a: int, b: int, x: float, threshold: float, limit: Optional[int] = None
) -> Optional[float]:
    """Overapproximate the regularised incomplete beta I_x(a, b).

    Iteratively evaluate I_x(a, b) with a hypergeometric
    representation.

    Stop with an approximate value as soon as we know if I_x(a, b) is
    less than or greater than threshold; the approximate value is on
    the same side of threshold.

    If the iteration limit is reached, return NIL.

    >>> 0 < _incbeta(5, 5, 0.001, 1.2558053968507e-13) \
          - 1.2558053968507e-13 < 2e-15
    True
    >>> 0 < _incbeta(100, 1000000, 1e-5, 5.425166381479153e-63) \
          - 5.425166381479153e-63 < 4e-69
    True
    >>> 0 < _incbeta(10000, 1, 0.999, 4.517334597704867e-05) \
          - 4.517334597704867e-05 < 5e-17
    True
    >>> _incbeta(10000, 1, 0.999, 4.517334597704867e-05, 10)
    >>> _incbeta(5, 5, 0.001, 1e-13) > 1e-13
    True
    >>> _incbeta(100, 1000000, 1e-5, 5.5e-63) < 5.5e-63
    True
    >>> _incbeta(5, 5, 0.1, 0.1)
    0.0008914881911461997
    >>> _incbeta(5, 5, 0.001, 1.2558053968507e-13)
    1.2566030059287187e-13
    >>> _incbeta(100, 1000000, 1e-5, 5.425166381479153e-63)
    5.42516983189825e-63
    >>> _incbeta(10000, 1, 0.999, 4.517334597704867e-05)
    4.5173345977071525e-05
    >>> _incbeta(5, 5, 0.001, 1e-13)
    1.2566030059287187e-13
    >>> _incbeta(100, 1000000, 1e-5, 5.5e-63)
    5.425170242086257e-63
    """
    assert x < (1.0 * a) / (a + b)
    if limit is None:
        limit = 10 * (a + b + 1000)

    log_initial = sum_up(
        robbins_log_choose(a + b - 1, a), next(a * log_up(x)), next(b * log1p_up(-x))
    )
    b_1 = b - 1.0
    # running product for the summands
    product = next(math.exp(log_initial), LIBM_ERROR_LIMIT)
    # Kahan summation pair.
    acc = (product, 0.0)
    for i in range(1, limit + 1):
        ratio = next(b_1 / (a + i))
        multiplicand = min(next(x * next(ratio + 1)), 1.0)
        old_acc = acc[0]
        product = next(product * multiplicand)
        acc = sum_update_up(acc, product)
        # Check for termination lazily.
        if acc[0] > threshold:
            # |acc[1]| < 1 ulp for acc.  It's always safe to report
            # _incbeta > threshold.
            return acc[0]
        if acc[0] != old_acc and i % 128 != 0:
            continue
        # Check for termination harder.
        tail_hi = product * math.exp(log_up(multiplicand) - log1p_down(-multiplicand))
        tail_lo = product * math.exp(log_down(x) - log1p_up(-x))
        # How much more do we have to clear to get to threshold?
        delta = (threshold - acc[0]) - acc[1]
        # If the lower bound on the tail is way more than delta, we
        # will definitely get there.
        if tail_lo > 2 * delta:
            # We know the result is > threshold.
            return max(acc[0] + tail_lo, threshold)
        # If the upper bound on the tail is way less than delta, we
        # know we'll never get there.
        if tail_hi < 0.5 * delta:
            return acc[0]
    # Did not find a bound in time.  Abort.
    return None


BETA_ICDF_EPS = 1e-10  # Always stop when we're this precise.

BETA_ICDF_GOAL = 1e-3  # Always try to get at least this precision.


def _beta_icdf_lo(a: int, b: int, alpha: float) -> Tuple[float, float]:
    """Underapproximate the left bound for a (1-2*alpha)-level CI on Beta(a, b).

    Maximise x s.t. I_x(a, b) < alpha < 0.5.  Assume x in (0, a / (a + b)).

    Iteratively tighten an interval with bisection search on a conservative
    upper bound of I_x(a, b).  The lower bound of the resulting interval is
    always a conservative lower bound on the inverse CDF for Beta(a, b).

    >>> _beta_icdf_lo(4, 4, 0.0)
    (0.0, 0.0)
    >>> 1 - 1e-2 < \
        _beta_icdf_lo(5, 5, 0.01)[0] / 0.1709651054824590931911 \
        <= 1.0
    True
    >>> 1 - 1e-4 < \
        _beta_icdf_lo(10000, 10, 0.0001)[0] / 0.9973853034151490539281 \
        <= 1.0
    True
    >>> 1 - 1e-6 < \
        _beta_icdf_lo(100, 1000000, 1e-8)[0] / 5.36173569850883957903e-5 \
        <= 1.0
    True
    >>> _beta_icdf_lo(5, 5, 0.01)
    (0.1709400317777181, 0.17094003179227002)
    >>> _beta_icdf_lo(10000, 10, 0.0001)
    (0.9973546960851649, 0.9974156702672328)
    >>> _beta_icdf_lo(100, 1000000, 1e-8)
    (5.361735618111455e-05, 5.361735618402464e-05)
    """
    assert 0 <= a < 1 << 44
    assert 0 <= b < 1 << 44
    assert 0.0 <= alpha < 0.5
    lo = 0.0
    hi = (1.0 * a) / (a + b)
    if alpha <= 0:
        return 0.0, 0.0

    while hi > max(BETA_ICDF_EPS, lo + lo * BETA_ICDF_EPS):
        x = 0.5 * (hi + lo)
        close_enough = hi < lo + lo * BETA_ICDF_GOAL
        limit = 1000 if close_enough else None
        px = _incbeta(a, b, x, alpha, limit)
        if px is None and close_enough:
            # time to leave!
            break
        if px is not None and px < alpha:
            lo = x
        else:
            hi = x

    return lo, hi


def beta_icdf(a: int, b: int, alpha: float, upper: bool = False) -> Tuple[float, float]:
    """Conservative (1 - 2*alpha) confidence interval bound for Beta(a, b).

    Compute a lower bound for the inverse CDF of Beta(a, b) at
    alpha. If upper, upper bound the inverse CDF at (1 - alpha).

    Assumes alpha is relatively small (at least 0.05); if that's not
    the case, force alpha to 0.05.

    Return the bound value, and an estimate of the (conservative)
    error on that bound.

    >>> beta_icdf(4, 4, 0.0)
    (0.0, 0.0)
    >>> beta_icdf(4, 4, 0.0, True)
    (1.0, 0.0)
    >>> 1 - 1e-2 < \
        beta_icdf(5, 5, 0.01)[0] / 0.1709651054824590931911 \
        <= 1.0
    True
    >>> 1 <= \
        beta_icdf(5, 5, 0.01, True)[0] / 0.8290348945175409068089 \
        < 1.0 + 1e-2
    True
    >>> 1 - 1e-4 < \
        beta_icdf(10000, 10, 0.0001)[0] / 0.9973853034151490539281 \
        <= 1.0
    True
    >>> 1 <= \
        beta_icdf(10000, 10, 0.0001, True)[0] / 0.9997803648233339942553 \
        < 1.0 + 1e-4
    True
    >>> 1 - 1e-6 < \
        beta_icdf(100, 1000000, 1e-8)[0] / 5.36173569850883957903e-5 \
        <= 1.0
    True
    >>> 1 <= \
        beta_icdf(100, 1000000, 1e-8, True)[0] / 1.666077240191560021563e-4 \
        < 1 + 2e-2
    True
    >>> beta_icdf(5, 5, 0.01)
    (0.1709400317777181, 1.4551915228366855e-11)
    >>> beta_icdf(5, 5, 0.01, True)
    (0.829059968222282, 1.4551915228366855e-11)
    >>> beta_icdf(10000, 10, 0.0001)
    (0.9973546960851649, 6.097418206785222e-05)
    >>> beta_icdf(10000, 10, 0.0001, True)
    (0.999780366628727, 1.4537362199446017e-14)
    >>> beta_icdf(100, 1000000, 1e-8)
    (5.361735618111455e-05, 2.9100934986411868e-15)
    >>> beta_icdf(100, 1000000, 1e-8, True)
    (0.0001686476860127684, 7.628631668143982e-06)
    """
    assert 0 < a < 1 << 44
    assert 0 < b < 1 << 44
    assert alpha >= 0
    if alpha <= 0:
        return (1.0, 0.0) if upper else (0.0, 0.0)
    alpha = min(alpha, 0.05)
    if upper:
        lo, hi = _beta_icdf_lo(b, a, alpha)
        return min(next(1 - lo), 1.0), min(next(hi - lo), 1.0)
    lo, hi = _beta_icdf_lo(a, b, alpha)
    return max(0.0, lo), min(next(hi - lo), 1.0)


# Basic utilities on top of CSM and beta_icdf.


def csm_driver(
    stream: Iterable[bool],
    alpha: float,
    eps: float,
    max_count: Optional[int] = None,
    min_count: Optional[int] = None,
    bound_eps: Optional[float] = None,
    file: Optional[IO[str]] = None,
) -> Tuple[bool, float, float, float]:
    """CSM test on a stream of i.i.d. booleans.

    Run a CSM test, given a stream of booleans.  Determines whether
    the success rate for generator is statistically different from
    alpha, with false positive rate < eps.

    Perform at least min-count iterations and at most max-count, if
    provided; log to out if non-NIL.

    On termination (successful or not), the return values are:

    1. Is the estimated success rate's probably different from alpha?
    2. The estimated success rate
    3. The lower end of 1 - bound-eps CI on the success rate
    4. The upper end of 1 - bound-eps CI on the success rate

    If the value in 1 is True, the odds that the estimated success
    rate and the actual success rates are on different sides of alpha
    are less than eps.  If bound_eps is not provided, we use eps.
    """
    assert 0 < alpha < 1
    assert 0 < eps <= 1
    log_eps = log_down(eps / 2)
    s = 0
    n = 0
    stop = False
    log_level = 0.0
    next_print = 0
    print_increment = 10

    def _bound(upper: bool) -> float:
        confidence = 0.5 * (eps / 2 if bound_eps is None else bound_eps)
        return beta_icdf(s + 1, (n - s) + 1, confidence, upper)[0]

    def _log_out() -> None:
        nonlocal next_print, print_increment
        # only print 10 times per power of 10.
        next_print += print_increment
        if next_print == 10 * print_increment:
            print_increment *= 10
        print(
            "%10d %.3f %.3f %.3f %.3f"
            % (
                n,
                1.0 * s / n,
                _bound(False),
                _bound(True),
                -log_level / math.log(10.0),
            ),
            file=file,
        )

    for success in stream:
        n += 1
        s += 1 if success else 0
        stop, log_level = csm(n, alpha, s, log_eps)
        if file is not None and n >= next_print:
            _log_out()
        if min_count is not None and n <= min_count:
            continue
        if stop:
            break
        if max_count is not None and n >= max_count:
            break
    return stop, 1.0 * s / n, _bound(False), _bound(True)


def csm_power(
    p: float,
    alpha: float,
    max_count: int,
    eps: float = 1e-5,
    success_rate: float = 0.99,
    file: Optional[IO[str]] = None,
) -> Tuple[bool, float, float, float]:
    """Power estimate for a CSM test.

    Estimate the probability of successfully determining that p and
    alpha differ, given max-count iterations and a target false
    positive rate of eps.

    Attempts to determine if the probability is less than or greater
    than the success rate 0.99 by default (with a false positive rate
    for that outer approximation of 1d-9).

    >>> csm_power(1.0, 0.99, 10, success_rate=0.99)[:2]
    (True, 0.0)
    >>> csm_power(0.0, 0.99, 10, success_rate=0.7)[:2]
    (True, 1.0)
    >>> csm_power(0.0, 0.99, 1, success_rate=0.7)[:2]
    (True, 0.0)
    >>> csm_power(1.0, 0.01, 10, success_rate=0.7, file=sys.stdout)
             1 1.000 0.000 1.000 -0.146
            10 1.000 0.143 1.000 0.508
            20 1.000 0.361 1.000 1.776
            30 1.000 0.501 1.000 3.156
            40 1.000 0.593 1.000 4.583
            50 1.000 0.657 1.000 6.038
            60 1.000 0.704 1.000 7.509
            70 1.000 0.740 1.000 8.992
    (True, 1.0, 0.7427095834561304, 1.0)
    >>> csm_power(1.0, 0.01, 1, success_rate=0.7)[:2]
    (True, 0.0)
    >>> csm_power(0.0, 0.01, 10, success_rate=0.99)[:2]
    (True, 0.0)
    """

    def _bernoulli() -> Iterator[bool]:
        while True:
            yield random.random() < p

    def _successes() -> Iterator[bool]:
        while True:
            ok, estimate, *_ = csm_driver(_bernoulli(), alpha, eps, max_count=max_count)
            if not ok:
                yield False
            elif p < alpha:
                yield estimate < alpha
            else:
                yield estimate > alpha

    return csm_driver(_successes(), success_rate, 1e-9, file=file)


if __name__ == "__main__":
    import doctest
    import sys

    doctest.testmod()
# Copyright 2018-2020, Paul Khuong
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Copyright 2018-2020, Paul Khuong
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
