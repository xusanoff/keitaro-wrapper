import pytest

from app.services.weights import WeightError, WeightItem, distribute, push_problem


def items(*specs):
    """spec: (status, pinned, share) tuples; position = index."""
    return [WeightItem(status=s, pinned=p, share=sh) for s, p, sh in specs]


def A(share=0, pinned=False):
    return ("active", pinned, share)


R = ("removed", False, 0)


def test_equal_split():
    assert distribute(items(A(), A(), A(), A())) == [25, 25, 25, 25]


def test_add_fourth_offer_to_three():
    assert distribute(items(A(33), A(33), A(34), A())) == [25, 25, 25, 25]


def test_remainder_goes_to_first_offers_by_position():
    assert distribute(items(A(), A(), A())) == [34, 33, 33]
    assert distribute(items(A(), A(), A(), A(), A(), A(), A())) == [15, 15, 14, 14, 14, 14, 14]
    assert sum(distribute(items(*[A()] * 7))) == 100


def test_single_offer_gets_100():
    assert distribute(items(A())) == [100]


def test_removed_offers_get_zero_and_do_not_count():
    assert distribute(items(A(), R, A(), R)) == [50, 0, 50, 0]


def test_pinned_kept_rest_split_evenly():
    # video example: pin one at 25, bring back another -> others share 75
    assert distribute(items(A(25, True), A(), A())) == [25, 38, 37]
    assert distribute(items(A(), A(25, True), A())) == [38, 25, 37]


def test_remainder_skips_pinned():
    assert distribute(items(A(10, True), A(), A(), A())) == [10, 30, 30, 30]
    assert distribute(items(A(), A(11, True), A(), A())) == [30, 11, 30, 29]


def test_multiple_pinned():
    assert distribute(items(A(20, True), A(30, True), A(), A())) == [20, 30, 25, 25]


def test_all_pinned_summing_to_100_is_valid():
    shares = distribute(items(A(60, True), A(40, True)))
    assert shares == [60, 40]
    assert push_problem(items(A(60, True), A(40, True))) is None


def test_all_pinned_not_100_blocks_push():
    it = items(A(60, True), A(30, True))
    assert distribute(it) == [60, 30]  # kept as is, user must fix
    assert "100" in push_problem(it)


def test_pinned_over_100_is_error():
    with pytest.raises(WeightError):
        distribute(items(A(70, True), A(40, True), A()))


def test_pinned_out_of_range_is_error():
    with pytest.raises(WeightError):
        distribute(items(A(-1, True), A()))
    with pytest.raises(WeightError):
        distribute(items(A(101, True)))


def test_pinned_flag_on_removed_offer_is_ignored():
    assert distribute(items(("removed", True, 50), A(), A())) == [0, 50, 50]


def test_pinned_100_leaves_zero_for_others():
    assert distribute(items(A(100, True), A(), A())) == [100, 0, 0]


def test_zero_active_offers():
    it = items(R, R)
    assert distribute(it) == [0, 0]
    assert push_problem(it) is not None
    assert push_problem([]) is not None


def test_push_problem_sum_check():
    assert push_problem(items(A(50), A(50), R)) is None
    assert push_problem(items(A(50), A(49))) is not None


@pytest.mark.parametrize("n", range(1, 30))
def test_always_sums_to_100(n):
    assert sum(distribute(items(*[A()] * n))) == 100
    assert sum(distribute(items(A(7, True), *[A()] * n))) == 100
