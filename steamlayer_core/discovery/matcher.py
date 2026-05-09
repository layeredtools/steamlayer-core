from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from steamlayer_core.utils import meaningful_tokens


class NameMatcher:
    SCENE_PATTERNS = [
        # --- Versioning & Technical Info ---
        r"\bv\d+([._]\d+)+\b",  # v15.1, v1.0.3, v1_0
        r"\bbuild\.\d+\b",  # e.g., build.12345
        r"\bmulti\d+\b",  # e.g., multi12
        # --- Repackers ---
        r"\bfitgirl\b",
        r"\bdodi\b",
        r"\belamigos\b",
        r"\bcygnus\b",
        r"\brepack(s)?\b",
        # --- Scene Groups ---
        r"\brune\b",
        r"\btenoke\b",
        r"\bskidrow\b",
        r"\bflt\b",
        r"\brazor1911\b",
        r"\bcodex\b",
        r"\breloaded\b",
        r"\bempress\b",
        r"\balias\b",
        r"\bgoldberg\b",
        # --- General Junk ---
        r"\bcrack\b",
        r"\bgog\b",
        r"\bproper\b",
        r"\binternal\b",
        r"\breadnfo\b",
        r"\bpreorder\b",
    ]

    BAD_TOKENS = {
        "soundtrack",
        "demo",
        "dlc",
        "beta",
        "test",
        "editor",
        "sdk",
        "tool",
        "kit",
    }

    EDITION_KEYWORDS = {"edition", "complete", "goty", "remastered", "ultimate", "deluxe", "remake", "game of the"}
    STOP_WORDS = {"the", "a", "an", "of", "in", "and", "or", "for"}

    def clean_name(self, name: str, is_folder: bool = True) -> str:
        name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")

        if is_folder:
            SCENE_RE = re.compile(rf"({'|'.join(self.SCENE_PATTERNS)})", re.IGNORECASE)
            name = SCENE_RE.sub("", name)

            year_match = re.search(r"(?:^|[\._ ])(19|20)\d{2}(?:[\._ ]|$)", name)
            if year_match:
                year_str = year_match.group()
                temp_clean = name.replace(year_str, " ").replace(".", " ").replace("_", " ")
                remaining_words = [w for w in temp_clean.split() if len(w) > 1]

                # If we have 2+ words (Resident Evil 4), the year is metadata.
                # If 1 word (DOOM), the year is Identity.
                if len(remaining_words) >= 2:
                    name = name.replace(year_str, " ")

        for char in [".", "_", "-", "[", "]"]:
            name = name.replace(char, " ")

        name = re.sub(r"([a-z])([A-Z])(?=[a-z])", r"\1 \2", name)
        name = name.lower()

        name = re.sub(r"[^a-z0-9\s:]", "", name)

        result = " ".join(name.split()).strip()

        # Collapse spaced letters (s t a l k e r -> stalker)
        result = re.sub(r"\b([a-z])\s(?=[a-z]\b)", r"\1", result)
        return result

    def calculate_confidence(self, target: str, candidate: str) -> float:
        clean_local = self.clean_name(target, is_folder=True)
        clean_steam = self.clean_name(candidate, is_folder=False)

        t_raw = re.sub(r"[^a-z0-9]", "", clean_local)
        c_raw = re.sub(r"[^a-z0-9]", "", clean_steam)

        if not t_raw or not c_raw:
            return 0.0

        if t_raw == c_raw:
            return 1.0

        ratio = SequenceMatcher(None, t_raw, c_raw).ratio()

        tokens_t = set(clean_local.replace(":", "").split())
        tokens_c = set(clean_steam.replace(":", "").split())
        meaningful_t = meaningful_tokens(tokens_t)
        meaningful_c = meaningful_tokens(tokens_c)

        core_t = clean_local
        for kw in self.EDITION_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", core_t):
                core_t = re.split(rf"\b{re.escape(kw)}\b", core_t)[0].strip()
                break

        core_t_raw = re.sub(r"[^a-z0-9]", "", core_t)
        if core_t_raw == c_raw and len(core_t_raw) > 3:
            ratio = max(ratio, 0.90)

        meaningful_shared = meaningful_t & meaningful_c
        if len(meaningful_shared) >= 2:
            ratio = max(ratio, 0.75)

        elif len(meaningful_shared) == 1:
            ratio = max(ratio, 0.55)

        numbers_t = re.findall(r"\d+", clean_local)
        numbers_c = re.findall(r"\d+", clean_steam)
        if numbers_t and numbers_t == numbers_c:
            ratio += 0.05

        is_subset = meaningful_t.issubset(meaningful_c) or meaningful_c.issubset(meaningful_t)
        if is_subset and len(meaningful_t) >= 2:
            ratio = max(ratio, 0.85)

        extra_tokens = tokens_c - tokens_t
        bad_extras = extra_tokens & self.BAD_TOKENS
        if bad_extras:
            ratio -= 0.25 * len(bad_extras)

        length_diff = abs(len(t_raw) - len(c_raw))
        ratio -= 0.01 * length_diff

        return round(max(0.0, min(1.0, ratio)), 2)
