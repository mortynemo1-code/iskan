import pytest

from app.screenshots import phash_distance


def test_phash_hamming_distance() -> None:
    assert phash_distance("0000000000000000", "0000000000000000") == 0
    assert phash_distance("0000000000000000", "000000000000000f") == 4
    assert phash_distance("ffffffffffffffff", "0000000000000000") == 64


def test_invalid_phash_is_rejected() -> None:
    with pytest.raises(ValueError):
        phash_distance("not-a-hash", "0000000000000000")
