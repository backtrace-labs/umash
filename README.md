UMASH: a fast almost universal 64-bit string hash
=================================================

[![amd64](https://github.com/backtrace-labs/umash/actions/workflows/run_tests_amd64.yml/badge.svg?event=push)](https://github.com/backtrace-labs/umash/actions/workflows/run_tests_amd64.yml) [![aarch64](https://github.com/backtrace-labs/umash/actions/workflows/run_tests_aarch64.yml/badge.svg?event=push)](https://github.com/backtrace-labs/umash/actions/workflows/run_tests_aarch64.yml)

STATUS: the hash and fingerprint algorithms are finalized, and so
is the mapping from `umash_params_derive` inputs to UMASH parameters.
However, the ABI is not finalized; in particular, passing random bytes
to `umash_params_prepare` may still result in different parameters.

UMASH is a string hash function with throughput (10.9 byte/cycle, or
39.5 GiB/s on an EPYC 7713) and latency (24 to 48 cycles for input
sizes up to 64 bytes on the same machine) comparable to that of
contemporary performance-optimised hashes like
[XXH3](https://github.com/Cyan4973/xxHash),
[HalftimeHash](https://github.com/jbapple/HalftimeHash),
or
[MeowHash](https://github.com/cmuratori/meow_hash)
(or [aHash](https://github.com/tkaitchuck/aHash/) for
[🦀 coders](https://github.com/backtrace-labs/umash-rs)).
Its 64-bit output is almost universal, and it, as well as both its
32-bit halves, passes both [Reini Urban's fork of
SMHasher](https://github.com/rurban/smhasher/) and [Yves Orton's
extended version](https://github.com/demerphq/smhasher) (after
expanding each seed to a 320-byte key for the latter).

This C library has also been ported to little-endian aarch64 with the
crypto extensions (`-march=armv8-a+crypto`).  On the Apple M1's 3.2
GHz performance cores, the port computes the same function as the
x86-64 implementation, at a peak throughput of 16 byte/cycle (49.2
GiB/s).

Unlike most other non-cryptographic hash functions
([CLHash](https://github.com/lemire/clhash) and
[HalftimeHash](https://github.com/jbapple/HalftimeHash) are rare
exceptions) which
[do not prevent seed-independent collisions](https://github.com/Cyan4973/xxHash/issues/180#issuecomment-474100780)
and thus [usually suffer from such weaknesses](https://www.131002.net/siphash/#at),
UMASH provably avoids parameter-independent collisions.  For any two
inputs of `s` bytes or fewer, the probability that a randomly
parameterised UMASH assigns them the same 64 bit hash value is less
than `ceil(s / 4096) 2**-55`.

UMASH also offers a fingerprinting function that computes a second
64-bit hash concurrently with the regular UMASH value.  That
function's throughput (7.5 byte/cycle, 25.8 GiB/s on an EPYC 7713) and
latency (37 to 74 cycles for inputs sizes up to 64 bytes on the same
machine) comparable to that of classic hash functions like
[MurmurHash3](https://github.com/aappleby/smhasher/wiki/MurmurHash3)
or [farmhash](https://github.com/google/farmhash).
Combining the two hashes yields a
[128-bit fingerprint](https://en.wikipedia.org/wiki/Fingerprint_(computing)#Virtual_uniqueness)
that collides pairs of `s`-or-fewer-byte inputs with probability less
than `ceil(s / 2**26)**2 * 2**-83`; that's less than `2**-70`
(`1e-21`) for up to 5 GiB of data.

See `umash_reference.py` (pre-rendered in `umash.pdf`) for details and
rationale about the design, and a proof sketch for the collision bound.
The [blog post announcing UMASH](https://engineering.backtrace.io/2020-08-24-umash-fast-enough-almost-universal-fingerprinting/),
and [this other post on the updated fingerprinting algorithm](https://pvk.ca/Blog/2020/10/31/nearly-double-the-ph-bits-with-one-more-clmul/)
include higher level overviews and may provide useful context.

If you're not into details, you can also just copy `umash.c` and
`umash.h` in your project: they're distributed under the MIT license.
For extra speed (at the expense of code size) add `umash_long.inc` as
well, also distributed under the MIT license.

The current implementation only build with gcc-compatible compilers
that support the [integer overflow builtins](https://gcc.gnu.org/onlinedocs/gcc/Integer-Overflow-Builtins.html)
introduced by GCC 5 (April 2015) and targets x86-64 machines with the
[CLMUL](https://en.wikipedia.org/wiki/CLMUL_instruction_set) extension
(available since 2011 on Intel and AMD), or aarch64 with the "crypto"
extension (for `PMULL`).

Quick start
-----------

Here's how to use UMASH for a simple batch hash or fingerprint
computation.

First, we need to generate `struct umash_params` that will define the
parameters ("key") of the UMASH hash or fingerprint function.

For a hashing use case, one could fill a `struct umash_params params`
with random bits (e.g., with
[a `getrandom(2)` syscall](https://man7.org/linux/man-pages/man2/getrandom.2.html)),
and call `umash_params_prepare(&params)` to convert the random bits
into a valid key.  This last call may fail by returning `false`;
however, the probability of that happening are astronomically small
(less than `2**-100`) if the input data is actually uniformly random.

Fingerprinting often needs a deterministic set of parameters that will
be preserved across program invocations.  For that use case, one
should either fill a `struct umash_params` with hardcoded random contents
before calling `umash_params_prepare`, or use `umash_params_derive` to
deterministically generate an unpredictable set of parameters from
a 64-bit value and a 32-byte secret.

For a fingerprinting use case, each program should use its own 32-byte
secret.

Given a fully initialised `struct umash_params params`, we can now
call `umash_full` or `umash_fprint` to hash or fingerprint a sequence
of bytes.  The `seed` argument is orthogonal to the collision bounds,
but may be used to get different values, e.g., when growing a hash
table afer too many collisions.  The fingerprint returned by
`umash_fprint` is simply an array of two hash values.  We can compute
either of these 64-bit hash values by calling `umash_full`: letting
`which = 0` computes the first hash value in the fingerprint, and
`which = 1` computes the second.  In practice, computing the second
hash value is as slow as computing a full fingerprint, so that's
rarely a good option.

See `example.c` for a quick example.

    $ cc -O2 -W -Wall example.c umash.c -mpclmul -o example
    $ ./example "the quick brown fox"
    Input: the quick brown fox
    Fingerprint: 398c5bb5cc113d03, 3a52693519575aba
    Hash 0: 398c5bb5cc113d03
    Hash 1: 3a52693519575aba

We can confirm that the parameters are constructed deterministically,
and that calling `umash_full` with `which = 0` or `which = 1` gets us
the two halves of the `umash_fprint` fingerprint.

Hacking on UMASH
----------------

The test suite calls into a shared object with test-only external
symbols with Python 3, [CFFI](https://cffi.readthedocs.io/en/latest/),
and [Hypothesis](https://hypothesis.works/).  As long as Python3 and
[venv](https://docs.python.org/3/library/venv.html) are installed, you
may execute `t/run-tests.sh` to download test dependencies, build the
current version of UMASH and run all the pytests in the `t/`
directory.  `t/run-tests-public.sh` only exercises the public
interface, which may be helpful to test a production build or when
making extensive internal changes.

The Python test code is automatically formatted with
[black](https://github.com/psf/black).  We try to make sure the C code
sticks to something similar to the
[FreeBSD KNF](https://www.freebsd.org/cgi/man.cgi?query=style&sektion=9);
when in doubt, whatever `t/format.sh` does is good enough.

We are also setting up Jupyter notebooks to make it easier to compare
different implementations, to visualise the results, and to
automatically run a set of statistical tests on that data. See
`bench/README.md` for more details.

Help wanted
-----------

The UMASH algorithm is now frozen, but the implementation isn't.  In
addition to regular maintenance and portability work, we are open to
expanding the library's capabilities. For example:

1. We currently only use incremental and one-shot hashing
   interfaces. If someone needs parallel hashing, we can collaborate
   to find out what that interface should look like.
2. How fast could we go on a GPU?
