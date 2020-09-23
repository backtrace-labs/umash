UMASH: a fast almost universal 64-bit string hash
=================================================

UMASH is a string hash function with throughput (22 GB/s on a 2.5 GHz
Xeon 8175M) and latency (9-22 ns for input sizes up to 64 bytes on
the same machine) comparable to that of performance-optimised hashes
like [MurmurHash3](https://github.com/aappleby/smhasher/wiki/MurmurHash3),
[XXH3](https://github.com/Cyan4973/xxHash), or
[farmhash](https://github.com/google/farmhash).  Its 64-bit output is
almost universal, and it, as well as both its 32-bit halves, passes
both [Reini Urban's fork of SMHasher](https://github.com/rurban/smhasher/)
and [Yves Orton's extended version](https://github.com/demerphq/smhasher) 
(after expanding each seed to a 320-byte key for the latter).

Unlike most other non-cryptographic hash functions
([CLHash](https://github.com/lemire/clhash) is a rare exception) which
[do not prevent seed-independent collisions](https://github.com/Cyan4973/xxHash/issues/180#issuecomment-474100780)
and thus [usually suffer from such weaknesses](https://www.131002.net/siphash/#at),
UMASH provably avoids parameter-independent collisions.  For any two
inputs of `l` bytes or fewer, the probability that a randomly
parameterised UMASH assigns them the same 64 bit hash value is less
than `ceil(l / 2048) 2**-56`.  UMASH also offers a fingerprinting mode
that simply computes two independent hashes at the same time.  The
resulting [128-bit fingerprint](https://en.wikipedia.org/wiki/Fingerprint_(computing)#Virtual_uniqueness)
collides pairs of `l`-or-fewer-byte inputs with probability less than
`ceil(l / 2048)**2 * 2**-112`; that's less than `2**-70` (`1e-21`) for
up to 7.5 GB of data.

See `umash_reference.py` (pre-rendered in `umash.pdf`) for details and
rationale about the design, and a proof sketch for the collision bound.
The [blog post announcing UMASH](https://engineering.backtrace.io/2020-08-24-umash-fast-enough-almost-universal-fingerprinting/)
includes a higher level overview and may also provide useful context.

If you're not into details, you can also just copy `umash.c` and
`umash.h` in your project: they're distributed under the MIT license.

The current implementation only build with gcc-compatible compilers
that support the [integer overflow builtins](https://gcc.gnu.org/onlinedocs/gcc/Integer-Overflow-Builtins.html)
introduced by GCC 5 (April 2015) and targets x86-64 machines with the
[CLMUL](https://en.wikipedia.org/wiki/CLMUL_instruction_set) extension
(available since 2011 on Intel and AMD).  That's simply because we
only use UMASH on such platforms at [Backtrace](https://backtrace.io/).
There should be no reason we can't also target other compilers, or
other architectures with carry-less multiplication instructions
(e.g., `VMULL` on ARMv8).

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
`which = 1` computes the second.

See `example.c` for a quick example.

    $ cc -O2 -W -Wall example.c umash.c -mpclmul -o example
    $ ./example "the quick brown fox"
    Input: the quick brown fox
    Fingerprint: 24783a0d59b0d2f0, d165a49500fdd4b6
    Hash 0: 24783a0d59b0d2f0
    Hash 1: d165a49500fdd4b6

We can confirm that the parameters are constructed deterministically,
and that calling `umash_full` with `which = 0` or `which = 1` gets us
the two halves of the `umash_fprint` fingerprint.

Please note that UMASH is still not fully finalised; while the source
code should be deterministic for a given revision, different revisions
may compute different values for the exact same inputs.

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

See `smhasher/HOWTO-SMHASHER.md` for patches to easily integrate UMASH
in the SMHasher hash performance and quality test suite.

We are also setting up Jupyter notebooks to make it easier to compare
different implementations, to visualise the results, and to
automatically run a set of statistical tests on that data. See
`bench/README.md` for more details.

Help wanted
-----------

While the UMASH algorithm isn't frozen yet, we do not expect to change
its overall structure (`PH` block compressor that feeds a polynomial
string hash).  There are plenty of lower hanging fruits.

1. The short (8 or fewer bytes) input code can hopefully be simpler.
2. The medium-length (9-16 bytes) input code path mixes an integer
   multiplication NH function's output with the same polynomial hash
   as the general case.  Can we further simplify that code sequence
   while maintaining the collision bound?
3. We only looked at x86-64 implementations; we will consider simple
   changes that improve performance on x86-64, or on other platforms
   as long they don't penalise x86-64.
4. We currently only use incremental and one-shot hashing
   interfaces. If someone needs parallel hashing, we can collaborate
   to find out what that interface could look like.

And of course, portability to other C compilers or platforms is
interesting.
