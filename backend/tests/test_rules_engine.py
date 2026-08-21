import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rules_engine import ClassificationRule, classify, matches


@dataclass
class Event:
    state: str = "NEUTRAL"
    process_name: str | None = None
    window_title: str | None = None
    url_domain: str | None = None
    url_path: str | None = None


class RulesEngineTests(unittest.TestCase):
    def test_priority_first_match_wins(self) -> None:
        rules = [
            ClassificationRule(20, "url_domain", "exact", "youtube.com", "NEUTRAL"),
            ClassificationRule(5, "url_full", "contains", "/shorts", "UNPRODUCTIVE"),
        ]
        event = Event(url_domain="youtube.com", url_path="/shorts/abc")
        self.assertEqual(classify(event, rules), "UNPRODUCTIVE")

    def test_process_matching_is_case_insensitive(self) -> None:
        rules = [ClassificationRule(1, "process_name", "exact", "code.exe", "PRODUCTIVE")]
        self.assertEqual(classify(Event(process_name="CODE.EXE"), rules), "PRODUCTIVE")

    def test_idle_is_not_overridden_by_category(self) -> None:
        rules = [ClassificationRule(1, "process_name", "wildcard", "*", "PRODUCTIVE")]
        self.assertEqual(classify(Event(state="IDLE", process_name="code.exe"), rules), "IDLE")

    def test_invalid_regex_does_not_match(self) -> None:
        self.assertFalse(matches("value", "regex", "["))


if __name__ == "__main__":
    unittest.main()
