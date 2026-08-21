import pytest

from app.admin_validation import validate_category_code, validate_hex_color, validate_rule_pattern


def test_category_code_is_normalized() -> None:
    assert validate_category_code(" Development-Team ") == "development-team"


@pytest.mark.parametrize("value", ["1invalid", "x", "кириллица", "has space"])
def test_category_code_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_category_code(value)


def test_color_is_normalized() -> None:
    assert validate_hex_color("#a1b2c3") == "#A1B2C3"


def test_invalid_regex_is_rejected() -> None:
    with pytest.raises(ValueError, match="регулярное выражение"):
        validate_rule_pattern("regex", "[")


def test_plain_pattern_is_trimmed() -> None:
    assert validate_rule_pattern("contains", "  youtube.com/shorts  ") == "youtube.com/shorts"
