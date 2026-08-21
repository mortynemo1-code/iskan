import re


CATEGORY_CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,49}$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_category_code(value: str) -> str:
    normalized = value.strip().lower()
    if not CATEGORY_CODE_RE.fullmatch(normalized):
        raise ValueError("Код должен начинаться с латинской буквы и содержать 2–50 символов")
    return normalized


def validate_hex_color(value: str) -> str:
    normalized = value.strip().upper()
    if not HEX_COLOR_RE.fullmatch(normalized):
        raise ValueError("Цвет должен быть в формате #RRGGBB")
    return normalized


def validate_rule_pattern(match_type: str, pattern: str) -> str:
    normalized = pattern.strip()
    if not normalized:
        raise ValueError("Шаблон правила не может быть пустым")
    if match_type == "regex":
        try:
            re.compile(normalized)
        except re.error as error:
            raise ValueError(f"Некорректное регулярное выражение: {error}") from error
    return normalized
