"""
Test suite for the UMASH parameter preparation function.
"""
import random
from hypothesis import example, given
import hypothesis.strategies as st
from umash import C, FFI
from umash_reference import umash, UmashKey


U64S = st.integers(min_value=0, max_value=2 ** 64 - 1)


FIELD = 2 ** 61 - 1


OH_COUNT = C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT


def assert_idempotent(params):
    """Asserts that calling `umash_params_prepare` on something that was
    successfully prepared is idempotent.
    """
    size = FFI.sizeof("struct umash_params")
    copy = FFI.new("struct umash_params[1]")
    FFI.memmove(copy, params, size)
    assert C.umash_params_prepare(copy) == True
    # The copy should still be the same as params.
    assert size % 8 == 0
    for i in range(size // 8):
        assert FFI.cast("uint64_t *", params)[i] == FFI.cast("uint64_t *", copy)[i]


@example(multipliers=[0, FIELD], random=random.Random(1))
@given(
    multipliers=st.lists(
        st.integers(min_value=1, max_value=FIELD - 1) | U64S, min_size=2, max_size=2
    ),
    random=st.randoms(note_method_calls=True, use_true_random=True),
)
def test_public_multiplier_reduction(multipliers, random):
    """Make sure multipliers are correctly reduced and rejected."""
    params = FFI.new("struct umash_params[1]")
    params[0].poly[0][0] = random.getrandbits(64)
    params[0].poly[0][1] = multipliers[0]
    params[0].poly[1][0] = random.getrandbits(64)
    params[0].poly[1][1] = multipliers[1]

    for i in range(OH_COUNT):
        params[0].oh[i] = i

    assert C.umash_params_prepare(params) == True
    assert_idempotent(params)
    for i in range(2):
        # If we passed in something clearly usable, it should be kept.
        if 0 < multipliers[i] < FIELD:
            assert params[0].poly[i][1] == multipliers[i]
        # The multipliers must be valid.
        assert 0 < params[0].poly[i][1] < FIELD
        assert params[0].poly[i][0] == (params[0].poly[i][1] ** 2) % FIELD

    # The OH params are valid.
    for i in range(C.UMASH_OH_PARAM_COUNT + C.UMASH_OH_TWISTING_COUNT):
        assert params[0].oh[i] == i


@example(oh=[0] * OH_COUNT, random=random.Random(1))
@given(
    oh=st.lists(
        st.integers(min_value=0, max_value=100), min_size=OH_COUNT, max_size=OH_COUNT
    ),
    random=st.randoms(note_method_calls=True, use_true_random=True),
)
def test_public_bad_oh(oh, random):
    """When the OH values repeat, we should replace them if we can.
    """
    repeated_values = len(oh) - len(set(oh))

    params = FFI.new("struct umash_params[1]")
    for i in range(2):
        params[0].poly[i][0] = random.getrandbits(64)
        params[0].poly[i][1] = random.getrandbits(64)

    for i, value in enumerate(oh):
        params[0].oh[i] = value

    result = C.umash_params_prepare(params)
    if repeated_values > 2:
        assert result == False
    if not result:
        return

    assert_idempotent(params)
    # On success, the OH parameters should be unique
    actual_oh = [params[0].oh[i] for i in range(OH_COUNT)]
    assert len(actual_oh) == len(set(actual_oh))


@given(
    random=st.randoms(note_method_calls=True, use_true_random=True),
    seed=U64S,
    data=st.binary(),
)
def test_public_smoke_matches(random, seed, data):
    """Prepare a params struct, and make sure the UMASH function matches
    our reference."""
    params = FFI.new("struct umash_params[1]")
    size = FFI.sizeof("struct umash_params")
    assert size % 8 == 0
    for i in range(size // 8):
        FFI.cast("uint64_t *", params)[i] = random.getrandbits(64)

    # Pseudorandom input should always succeed.
    assert C.umash_params_prepare(params) == True
    assert_idempotent(params)
    expected0 = umash(
        UmashKey(params[0].poly[0][1], [params[0].oh[i] for i in range(OH_COUNT)]),
        seed,
        data,
        secondary=False,
    )
    assert C.umash_full(params, seed, 0, data, len(data)) == expected0

    expected1 = umash(
        UmashKey(params[0].poly[1][1], [params[0].oh[i] for i in range(OH_COUNT)],),
        seed,
        data,
        secondary=True,
    )
    assert C.umash_full(params, seed, 1, data, len(data)) == expected1
