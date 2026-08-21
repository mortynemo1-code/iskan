import fnmatch
import re
from dataclasses import dataclass
from typing import Protocol


PRESERVED_STATES = {"IDLE", "LOCKED", "BREAK"}


class ClassifiableEvent(Protocol):
    state: str
    process_name: str | None
    window_title: str | None
    url_domain: str | None
    url_path: str | None


@dataclass(frozen=True)
class ClassificationRule:
    priority: int
    match_field: str
    match_type: str
    pattern: str
    productivity: str
    category_id: int | None = None


@dataclass(frozen=True)
class ClassificationResult:
    state: str
    category_id: int | None


def event_field(event: ClassifiableEvent, field: str) -> str:
    if field == "process_name":
        return event.process_name or ""
    if field == "window_title":
        return event.window_title or ""
    if field == "url_domain":
        return event.url_domain or ""
    if field == "url_full":
        domain = event.url_domain or ""
        path = event.url_path or ""
        return f"{domain}{path}"
    return ""


def matches(value: str, match_type: str, pattern: str) -> bool:
    value_folded = value.casefold()
    pattern_folded = pattern.casefold()
    if match_type == "exact":
        return value_folded == pattern_folded
    if match_type == "contains":
        return pattern_folded in value_folded
    if match_type == "wildcard":
        return fnmatch.fnmatchcase(value_folded, pattern_folded)
    if match_type == "regex":
        if len(pattern) > 500:
            return False
        try:
            return re.search(pattern, value, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def classify(event: ClassifiableEvent, rules: list[ClassificationRule]) -> str:
    return classify_result(event, rules).state


def classify_result(event: ClassifiableEvent, rules: list[ClassificationRule]) -> ClassificationResult:
    normalized_state = event.state.upper()
    if normalized_state in PRESERVED_STATES:
        return ClassificationResult(normalized_state, None)
    for rule in sorted(rules, key=lambda item: item.priority):
        if matches(event_field(event, rule.match_field), rule.match_type, rule.pattern):
            return ClassificationResult(rule.productivity, rule.category_id)
    return ClassificationResult("NEUTRAL", None)
