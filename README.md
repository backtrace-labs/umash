UMASH: a fast almost universal 64-bit string hash
=================================================

UMASH is a string hash function with throughput---22 GB/s on a 2.5 GHz
Xeon 8175M---and latency---9-22 ns for input sizes up to 64 bytes on
the same machine---comparable to that of performance-optimised hashes
like [MurmurHash3](https://github.com/aappleby/smhasher/wiki/MurmurHash3),
[XXH3](https://github.com/Cyan4973/xxHash), or
[farmhash](https://github.com/google/farmhash).  Its 64-bit output is
almost universal, and it, as well as both its 32-bit halves, passes
both [Reini Urban's fork of SMHasher](https://github.com/rurban/smhasher/)
and [Yves Orton's extended version](https://github.com/demerphq/smhasher) 
(after expanding each seed to a full 320-byte key for the latter).

See `umash_reference.py` (pre-rendered as `umash.pdf`) for details and
rationale about the design, and proof that two inputs of `l` bytes of
fewer are assigned the same 64-bit hash with probability less than
`ceil(l / 2048) 2**-56`.

If you're not into details, you can also just copy `umash.c` and
`umash.h` in your project: they're distributed under the MIT license.

The current implementation only build with gcc-compatible compilers
that support the [integer overflow builtins](https://gcc.gnu.org/onlinedocs/gcc/Integer-Overflow-Builtins.html)
introduced by GCC 5 (April 2015) and targets x86-64 machines with the
CLMUL extension (available since 2011 on Intel and AMD).  That's simply
because we only use UMASH on such platforms at Backtrace.  There should
be no reason we can't also target other compilers, or other architectures
with finite field multiplication instructions (e.g., `VMULL` on ARMv8).

Hacking on UMASH
----------------

The test suite calls into a shared object with test-only external
symbols with Python 3, [CFFI](https://cffi.readthedocs.io/en/latest/),
and [Hypothesis](https://hypothesis.works/).  As long as Python3 and
[venv](https://docs.python.org/3/library/venv.html) are installed, you
may run `t/run-tests.sh` to build the current version of umash and run
all the pytests in the `t/` directory.  `t/run-tests-public.sh` focus
on the public interface, which may be helpful to test a production
build or when making extensive internal changes.

The Python test code is automatically formatted with
[black](https://github.com/psf/black).  We try to make sure the C code
sticks to something like the FreeBSD KNF; when in doubt, whatever
`t/format.sh` does is good enough.

Help wanted
-----------

While the UMASH algorithm isn't frozen yet, we do not expect to change
its overall structure (`PH` block compressor that feeds a polynomial
string hash).  There are plenty of lower hanging fruits.

1. The short (8 or fewer bytes) input code can hopefully be simpler.
2. The medium-length (9-15 bytes) input code path is a micro-optimised
   version of the general case, but does not actually share any
   machine code; can we improve the latency and maintain the collision
   bounds by replacing it with something completely different?
3. It’s already nice that we can get away with a single round of
   `xor-shift` / multiply in the finaliser, but can we shave even more
   latency there?
4. We only looked at x86-64 implementations; we will consider simple
   changes that improve performance on other platforms without
   penalising x86-64.
5. We currently only use incremental and one-shot hashing
   interfaces. If someone needs parallel hashing, we can collaborate
   to find out what that interface could look like.

And of course, portability to other C compilers or platforms is
interesting.
