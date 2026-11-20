import pytest

from app.shortener import (
    decode_base62,
    encode_base62,
)


@pytest.mark.parametrize(
    "number",
    [0, 1, 10, 61, 62, 125, 1000, 999999],
)
def test_roundtrip(number):
    assert decode_base62(
        encode_base62(number)
    ) == number


def test_known_values():
    assert encode_base62(10) == "a"
    assert encode_base62(61) == "Z"
    assert encode_base62(62) == "10"


def test_negative_id():
    with pytest.raises(ValueError):
        encode_base62(-1)


def test_invalid_character():
    with pytest.raises(ValueError):
        decode_base62("!")
