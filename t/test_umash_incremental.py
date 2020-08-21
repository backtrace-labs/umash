"""Test suite for the incremental hashing and fingerprinting
interfaces.  Compares their results with the batch implementation and
the reference implementation.
"""
from hypothesis import note
from hypothesis.stateful import (
    initialize,
    invariant,
    precondition,
    rule,
    RuleBasedStateMachine,
)
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import umash, UmashKey

U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)


FIELD = 2 ** 61 - 1


def umash_params():
    """Generates a UMASH parameter tuple."""

    def make_params(multipliers, ph):
        params = FFI.new("struct umash_params[1]")
        for i, multiplier in enumerate(multipliers):
            params[0].poly[i][0] = (multiplier ** 2) % FIELD
            params[0].poly[i][1] = multiplier
        for i, param in enumerate(ph):
            params[0].ph[i] = param

        return (multipliers, ph, params)

    return st.builds(
        make_params,
        st.lists(st.integers(min_value=0, max_value=FIELD - 1), min_size=2, max_size=2),
        st.lists(
            # We need 4 more PH values for the Toeplitz shift.
            U64S,
            min_size=C.UMASH_PH_PARAM_COUNT + 4,
            max_size=C.UMASH_PH_PARAM_COUNT + 4,
        ),
    )


class IncrementalUpdater(RuleBasedStateMachine):
    """Calls self.update with various byte buffers.

    Child classes are expected to:

    - define an @initialize rule to set the UMASH state
    - define reference_value() to compute the reference hash of self.acc
    - define batch_value() to compute the batch hash of self.acc
    - define digest_value() to extract the current incremental digest
    - update(buf, n) to feed buf[0 ... n - 1] to the incremental state
    """

    def __init__(self):
        super().__init__()
        self.multipliers = None
        self.ph = None
        self.params = None
        self.state = None
        self.acc = b""

    @invariant()
    def compare_values(self):
        if self.state is None:
            return

        reference = self.reference_value()
        batch = self.batch_value()
        actual = self.digest_value()

        note((len(self.acc), self.acc))
        assert reference == batch == actual, {
            "ref": reference,
            "batch": batch,
            "actual": actual,
        }

    def _update(self, buf):
        self.acc += buf
        n = len(buf)
        # Copy to the heap to help ASan
        copy = FFI.new("char[]", n)
        FFI.memmove(copy, buf, n)
        self.update(copy, n)

    @precondition(lambda self: self.state)
    @rule(buf=st.binary())
    def update_short(self, buf):
        note("update_short: %s" % len(buf))
        self._update(buf)

    @precondition(lambda self: self.state)
    @rule(
        num=st.integers(min_value=1, max_value=1024),
        byte=st.binary(min_size=1, max_size=1),
    )
    def update_repeat(self, num, byte):
        buf = byte * num
        self._update(buf)

    @precondition(lambda self: self.state)
    @rule(
        length=st.integers(min_value=1, max_value=1024),
        random=st.randoms(use_true_random=True),
    )
    def update_long(self, length, random):
        buf = bytes((random.getrandbits(8) for _ in range(length)))
        note("update_long: %s" % buf)
        self._update(buf)


class IncrementalHasher(IncrementalUpdater):
    def __init__(self):
        super().__init__()
        self.seed = None
        self.which = None

    @initialize(
        params=umash_params(), seed=U64S, which=st.integers(min_value=0, max_value=1)
    )
    def create_state(self, params, seed, which):
        self.multipliers, self.ph, self.params = params
        self.state = FFI.new("struct umash_state[1]")
        self.sink = FFI.addressof(self.state[0].sink)
        C.umash_init(self.state, self.params, seed, which)
        self.seed = seed
        self.which = which

    def update(self, buf, n):
        C.umash_sink_update(self.sink, buf, n)

    def reference_value(self):
        return umash(
            UmashKey(
                poly=self.multipliers[self.which],
                ph=self.ph[self.which * C.UMASH_PH_TOEPLITZ_SHIFT :],
            ),
            self.seed,
            self.acc,
        )

    def batch_value(self):
        return C.umash_full(self.params, self.seed, self.which, self.acc, len(self.acc))

    def digest_value(self):
        return C.umash_digest(self.state)


test_public_incremental_hasher = IncrementalHasher.TestCase


class IncrementalFprinter(IncrementalUpdater):
    def __init__(self):
        super().__init__()
        self.seed = None

    @initialize(params=umash_params(), seed=U64S)
    def create_state(self, params, seed):
        self.multipliers, self.ph, self.params = params
        self.state = FFI.new("struct umash_fp_state[1]")
        self.sink = FFI.addressof(self.state[0].sink)
        C.umash_fp_init(self.state, self.params, seed)
        self.seed = seed

    def update(self, buf, n):
        C.umash_sink_update(self.sink, buf, n)

    def reference_value(self):
        return [
            umash(
                UmashKey(
                    poly=self.multipliers[which],
                    ph=self.ph[which * C.UMASH_PH_TOEPLITZ_SHIFT :],
                ),
                self.seed,
                self.acc,
            )
            for which in range(2)
        ]

    def batch_value(self):
        result = C.umash_fprint(self.params, self.seed, self.acc, len(self.acc))
        return [result.hash[0], result.hash[1]]

    def digest_value(self):
        result = C.umash_fp_digest(self.state)
        return [result.hash[0], result.hash[1]]


test_public_incremental_fprinter = IncrementalFprinter.TestCase
