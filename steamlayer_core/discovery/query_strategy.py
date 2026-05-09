from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steamlayer_core.discovery.matcher import NameMatcher


class QueryStrategy:
    """
    Strategy:
    1. Try full name (normalized)
    2. Split by subtitle (captions)
    3. Remove version modifiers
    4. Remove common stopwords
    5. Simplify to first two words
    6. Simplify to first word
    7. Remove standalone numbers
    """

    MODIFIERS = {
        "remake",
        "remastered",
        "goty",
        "edition",
        "complete",
        "bundle",
        "deluxe",
        "ultimate",
    }

    STOPWORDS = {"the", "a", "an"}

    def __init__(self, matcher: NameMatcher) -> None:
        self.matcher = matcher

    def _remove_stopwords(self, name: str) -> str:
        words = name.split()
        filtered = [w for w in words if w not in self.STOPWORDS]
        return " ".join(filtered)

    def _remove_modifiers(self, name: str) -> str:
        words = name.split()
        filtered = [w for w in words if w not in self.MODIFIERS]
        return " ".join(filtered)

    def generate(self, name: str) -> list[str]:
        queries: list[str] = []

        raw_base = self.matcher.clean_name(name)

        queries.append(name)
        queries.append(raw_base)

        if ":" in raw_base:
            main_part = raw_base.split(":")[0].strip()
            if main_part:
                queries.append(main_part)

        clean_base = raw_base.replace(":", " ")
        clean_base = " ".join(clean_base.split())
        words = clean_base.split()

        no_modifiers = self._remove_modifiers(clean_base)
        if no_modifiers and no_modifiers != clean_base:
            queries.append(no_modifiers)

        no_stop = self._remove_stopwords(no_modifiers)
        if no_stop and no_stop != no_modifiers:
            queries.append(no_stop)

        if len(words) >= 2:
            if len(words) >= 3 and (words[2].isdigit() or len(words[2]) <= 2):
                queries.append(" ".join(words[:3]))
            else:
                queries.append(" ".join(words[:2]))

        if words:
            first = words[0]
            if first not in self.STOPWORDS:
                queries.append(first)
            elif len(words) >= 2:
                queries.append(words[1])

        no_numbers = re.sub(r"\b\d+\b", "", no_modifiers).strip()
        if no_numbers and no_numbers != no_modifiers:
            no_numbers = " ".join(no_numbers.split())
            if no_numbers:
                queries.append(no_numbers)

        seen = set()
        result = []
        for q in queries:
            if q and q not in seen:
                result.append(q)
                seen.add(q)

        return result
