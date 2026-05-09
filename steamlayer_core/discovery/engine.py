"""
steamlayer_core.resolution.engine
==================================
The ``ResolutionEngine`` is the authoritative implementation of the AppID
waterfall. This class:

1. Has zero I/O dependencies — all human-interaction is delegated to
   injected ``DisambiguationHandler`` / ``ConfirmationHandler`` callables.
2. Emits progress via an optional ``ProgressCallback``.
3. Raises typed domain exceptions rather than returning sentinel values.
4. Is covered by a deterministic test suite (see ``tests/heuristics/``).

Waterfall order
---------------
1. Manual AppID  (caller supplied ``options.appid``)
2. Local file    (``steam_appid.txt`` or ``.acf`` manifest scan)
3. Local index   (community JSON mirror on disk)
4. Web search    (Steam Store search API with query generation)
→  Disambiguation / confirmation prompt on tie or low confidence

The engine is *not* responsible for DLC hydration — that lives in
``DLCService``, which is called by the public ``api.resolve_game()`` function.
"""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass, field

from steamlayer_core.discovery.local import LocalDiscovery
from steamlayer_core.discovery.matcher import NameMatcher
from steamlayer_core.discovery.query_strategy import QueryStrategy
from steamlayer_core.discovery.repository import AppIndexRepository
from steamlayer_core.events import AmbiguousMatchEvent, LowConfidenceEvent
from steamlayer_core.domain.exceptions import AppIDNotFoundError
from steamlayer_core.domain.models import DiscoveryResult, ResolutionSource, ResolvedGame, SteamlayerOptions
from steamlayer_core.protocols import (
    NULL_PROGRESS,
    ConfirmationHandler,
    DisambiguationHandler,
    ProgressCallback,
    SteamWebClientProtocol,
)
from steamlayer_core.utils import STOP_WORDS, meaningful_tokens

log = logging.getLogger("steamlayer_core.resolution.engine")

STRICT_THRESHOLD = 0.85
YOLO_THRESHOLD = 0.40
AMBIGUITY_GAP = 0.10  # scores closer than this trigger disambiguation
AMBIGUITY_MIN_SCORE = 0.50  # scores below this are never considered ambiguous


def _contains_as_words(needle: str, haystack: str) -> bool:
    needle_words = set(needle.split()) - STOP_WORDS
    if not needle_words:
        return False

    haystack_words = set(haystack.split())
    return needle_words.issubset(haystack_words)


@dataclass
class _Resolution:
    """Internal accumulator — never leaves this module."""

    candidates: list[DiscoveryResult] = field(default_factory=list)
    queries_tried: list[str] = field(default_factory=list)


class ResolutionEngine:
    """
    Orchestrates the AppID waterfall and delegates user-interaction events
    to injected handlers.

    Parameters
    ----------
    local_discovery:
        Scans the game folder for ``steam_appid.txt`` / ``.acf`` manifests.
    app_index_repository:
        Provides the community App/DLC JSON index.
    steam_web_client:
        Wraps the Steam Store search and details APIs.
    name_matcher:
        Scores string similarity between a folder name and a Steam title.
    query_strategy:
        Generates a ranked list of search queries from a raw folder name.
    """

    def __init__(
        self,
        *,
        local_discovery: LocalDiscovery,
        app_index_repository: AppIndexRepository,
        steam_web_client: SteamWebClientProtocol,
        name_matcher: NameMatcher,
        query_strategy: QueryStrategy,
    ) -> None:
        self._local = local_discovery
        self._repo = app_index_repository
        self._web = steam_web_client
        self._matcher = name_matcher
        self._query_strategy = query_strategy

    def resolve(
        self,
        game_path: pathlib.Path,
        options: SteamlayerOptions,
        *,
        allow_network: bool,
        on_disambiguation: DisambiguationHandler | None = None,
        on_confirmation: ConfirmationHandler | None = None,
        progress: ProgressCallback = NULL_PROGRESS,
    ) -> DiscoveryResult:
        """
        Resolve the AppID for a game folder.

        Parameters
        ----------
        game_path:
            Path to the game's root directory.
        options:
            Controls thresholds, network access, and explicit AppID overrides.
        allow_network:
            Wether we should search for AppIDs online or only locally.
        on_disambiguation:
            Called when candidates are too close to auto-select.  If ``None``
            and disambiguation is needed, raises ``AmbiguousMatchError``.
        on_confirmation:
            Called when the best candidate is below the acceptance threshold.
            If ``None`` and confirmation is needed, raises ``LowConfidenceError``.
        progress:
            Optional hook for surfacing progress steps to a UI.

        Returns
        -------
        DiscoveryResult
            A result whose ``appid`` is always non-None on success.

        Raises
        ------
        AppIDNotFound
            When no candidate could be found at all.
        AmbiguousMatchError
            When disambiguation is needed but no handler was provided.
        LowConfidenceError
            When confirmation is needed but no handler was provided.
        """
        folder_name = game_path.name
        acc = _Resolution()

        if options.appid is not None:
            log.debug("AppID provided manually: %d", options.appid)
            return DiscoveryResult(
                appid=options.appid,
                source=ResolutionSource.MANUAL,
                confidence=1.0,
            )

        progress("local_scan", f"Scanning '{folder_name}' for steam_appid.txt / .acf…")
        local_id = self._local.find(game_path)
        if local_id:
            log.info("Found AppID %d via local file scan.", local_id)
            return DiscoveryResult(
                appid=local_id,
                source=ResolutionSource.LOCAL_FILE,
                confidence=1.0,
            )

        progress("local_index", "Checking local community index…")
        index_result = self._search_local_index(folder_name)
        if index_result.appid is not None:
            if index_result.confidence >= STRICT_THRESHOLD:
                log.info(
                    "High-confidence local index hit: %s (%.0f%%)",
                    index_result.appid,
                    index_result.confidence * 100,
                )
                return index_result

            if index_result.confidence > YOLO_THRESHOLD:
                acc.candidates.append(index_result)

        if allow_network:
            progress("web_search", f"Searching Steam for '{folder_name}'…")
            queries = self._query_strategy.generate(folder_name)
            acc.queries_tried.extend(queries)
            self._run_web_search(folder_name, queries, acc)
        else:
            log.warning("Network disabled — skipping Steam search.")

        if not acc.candidates:
            raise AppIDNotFoundError(str(game_path))

        return self._make_decision(
            acc=acc,
            folder_name=folder_name,
            options=options,
            on_disambiguation=on_disambiguation,
            on_confirmation=on_confirmation,
        )

    def _search_local_index(self, folder_name: str) -> DiscoveryResult:
        index = self._repo.get_app_index()
        name_map = self._repo.get_app_name_map()
        if not index:
            return DiscoveryResult()

        clean = self._matcher.clean_name(folder_name).lower()
        if clean in index:
            return DiscoveryResult(
                appid=index[clean],
                source=ResolutionSource.LOCAL_INDEX,
                confidence=1.0,
                game_name=name_map.get(clean, clean),
            )

        best = DiscoveryResult(confidence=0.0)
        for raw_name, appid in index.items():
            clean_idx = self._matcher.clean_name(raw_name, is_folder=False)
            if not (_contains_as_words(clean, clean_idx) or _contains_as_words(clean_idx, clean)):
                continue

            conf = self._matcher.calculate_confidence(clean, clean_idx)
            if conf > best.confidence:
                best = DiscoveryResult(
                    appid=appid,
                    source=ResolutionSource.LOCAL_INDEX,
                    confidence=conf,
                    game_name=name_map.get(raw_name, raw_name),
                )
            if best.confidence >= 1.0:
                break

        return best

    def _run_web_search(self, folder_name: str, queries: list[str], acc: _Resolution) -> None:
        seen_appids = set()

        for query in queries:
            log.debug("Web query: '%s'", query)
            try:
                data = self._web.search_store(query)
            except Exception as exc:
                log.warning("Web search for '%s' failed: %s", query, exc)
                continue

            if not data.get("total"):
                continue

            perfect_hit = False

            for item in data.get("items", [])[:15]:
                if item.get("type") != "app":
                    continue

                appid = int(item["id"])
                if appid in seen_appids:
                    continue

                seen_appids.add(appid)

                steam_name: str = item["name"]
                score: float = self._matcher.calculate_confidence(folder_name, steam_name)

                if score < 1.0:
                    for sep in (":", " - "):
                        if sep in steam_name:
                            left, right = steam_name.split(sep, 1)

                            left = left.strip()
                            left_ratio = len(left) / len(steam_name)
                            partial_score = self._matcher.calculate_confidence(folder_name, left) * left_ratio
                            score = max(score, partial_score)
                            if score >= 1.0:
                                break

                            right = right.strip()
                            right_ratio = len(right) / len(steam_name)
                            score = max(
                                score, self._matcher.calculate_confidence(folder_name, right) * right_ratio
                            )

                            if score >= 1.0:
                                break

                if score > YOLO_THRESHOLD:
                    acc.candidates.append(
                        DiscoveryResult(
                            appid=appid,
                            game_name=steam_name,
                            confidence=score,
                            source=ResolutionSource.WEB_SEARCH,
                        )
                    )

                if score >= 1.0:
                    perfect_hit = True
                    break

            if perfect_hit:
                log.debug("Perfect hit found — stopping web search early.")
                break

    def _make_decision(
        self,
        *,
        acc: _Resolution,
        folder_name: str,
        options: SteamlayerOptions,
        on_disambiguation: DisambiguationHandler | None,
        on_confirmation: ConfirmationHandler | None,
    ) -> DiscoveryResult:
        """Select the best candidate, handling ties and low-confidence cases."""
        from steamlayer_core.domain.exceptions import AmbiguousMatchError, LowConfidenceError

        seen: dict[int | None, DiscoveryResult] = {}
        event: AmbiguousMatchEvent | LowConfidenceEvent
        for c in acc.candidates:
            if c.appid not in seen or c.confidence > seen[c.appid].confidence:
                seen[c.appid] = c
        ranked = sorted(seen.values(), key=lambda r: r.confidence, reverse=True)

        best = ranked[0]
        threshold = STRICT_THRESHOLD if options.strict else YOLO_THRESHOLD

        if len(ranked) > 1:
            second = ranked[1]
            if self._is_ambiguous(best, second, folder_name) and best.confidence < 1.0:
                log.info("Ambiguous match — top candidates: %s vs %s", best, second)
                event = AmbiguousMatchEvent(
                    candidates=tuple(ranked[:9]),
                    game_folder_name=folder_name,
                )
                if on_disambiguation is None:
                    public_candidates = [
                        ResolvedGame(
                            appid=c.appid,  # type: ignore
                            game_name=c.game_name,
                            source=c.source,
                            confidence=c.confidence,
                            dlcs={},
                        )
                        for c in event.candidates
                    ]
                    raise AmbiguousMatchError(public_candidates)
                return on_disambiguation(event)

        if not self._should_accept(best.confidence, threshold):
            log.info("Low confidence: %s (threshold %.0f%%)", best, threshold * 100)
            event = LowConfidenceEvent(
                candidate=best,
                threshold=threshold,
                game_folder_name=folder_name,
            )
            if on_confirmation is None:
                raise LowConfidenceError(
                    ResolvedGame(
                        appid=best.appid,  # type: ignore
                        game_name=best.game_name,
                        confidence=best.confidence,
                        source=best.source,
                        dlcs=None,
                    ),
                    threshold=threshold,
                )
            return on_confirmation(event)

        log.info("Accepted: %s", best)
        return best

    @staticmethod
    def _is_ambiguous(best: DiscoveryResult, second: DiscoveryResult, target_name: str) -> bool:
        if best.confidence < AMBIGUITY_MIN_SCORE:
            return False

        if (best.confidence - second.confidence) < AMBIGUITY_GAP:
            return True

        target_words = meaningful_tokens(set(target_name.lower().split()))
        second_words = meaningful_tokens(set((second.game_name or "").lower().split()))
        shared = target_words & second_words
        if target_words and len(shared) > len(target_words) * 0.5:
            return True

        return False

    @staticmethod
    def _should_accept(score: float, threshold: float) -> bool:
        return score >= threshold
