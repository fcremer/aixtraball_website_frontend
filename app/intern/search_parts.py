"""
Fuzzy search for spare parts.
Ported and optimised from the standalone parts app (rapidfuzz-based).
"""

from __future__ import annotations

import re
import time
from typing import Any

try:
    from rapidfuzz import fuzz, process, utils as rf_utils
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

MIN_SCORE = 55
MAX_CANDIDATES = 120
_TOKEN_RE = re.compile(
    r"[A-Za-zÄÖÜäöüß0-9]+(?:[.,/\-][A-Za-zÄÖÜäöüß0-9]+)*",
    re.I,
)

# In-memory cache: (parts_list, timestamp)
_cache: tuple[list[dict], float] | None = None
_CACHE_TTL = 30.0  # seconds


def invalidate_cache() -> None:
    global _cache
    _cache = None


def get_cached_parts(loader_fn) -> list[dict]:
    """Return cached part dicts, refreshing if stale."""
    global _cache
    now = time.monotonic()
    if _cache is None or (now - _cache[1]) > _CACHE_TTL:
        parts = loader_fn()
        _cache = (parts, now)
    return _cache[0]


# ── normalisation helpers ────────────────────────────────────────────────────

def _norm_slash(v: str) -> str:
    return re.sub(r"\s*/\s*", "/", v)


def _norm_token(v: str) -> str:
    return _norm_slash(v).lower().replace(",", ".").strip()


def _norm_alnum(v: str) -> str:
    return re.sub(r"[^A-Za-zÄÖÜäöüß0-9]", "", v).lower()


def _candidate_tokens(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        out.append(tok)
        if "/" in tok or "-" in tok:
            for part in re.split(r"[/\-]", tok):
                p = part.strip()
                if p:
                    out.append(p)
    return out


# ── choice building ──────────────────────────────────────────────────────────

def _build_choices(parts: list[dict]) -> list[tuple[str, int]]:
    choices: list[tuple[str, int]] = []
    for p in parts:
        pid = int(p["id"])
        seen: set[str] = set()

        shelf, bin_ = p.get("shelf"), p.get("bin")
        candidates = [p.get("name"), p.get("article_number"), p.get("supplier"), shelf, bin_]
        for v in candidates:
            if v:
                t = str(v).strip()
                if t and t not in seen:
                    choices.append((t, pid))
                    seen.add(t)

        # shelf+bin combined
        if shelf or bin_:
            for sep in (" ", "/"):
                combo = sep.join(str(x).strip() for x in (shelf, bin_) if x)
                if combo and combo not in seen:
                    choices.append((combo, pid))
                    seen.add(combo)

        for s in p.get("synonyms", []):
            t = str(s).strip()
            if t and t not in seen:
                choices.append((t, pid))
                seen.add(t)

        for m in p.get("manufacturers", []):
            t = str(m).strip()
            if t and t not in seen:
                choices.append((t, pid))
                seen.add(t)

    return choices


# ── core search ──────────────────────────────────────────────────────────────

def search_parts(parts: list[dict], query: str, limit: int = 30) -> list[dict]:
    """
    Hybrid exact + fuzzy search.  Returns up to `limit` parts ranked by score.
    Falls back to simple substring search if rapidfuzz is not installed.
    """
    query = query.strip()
    if not query:
        return parts[:limit]
    if not parts:
        return []

    if not _HAS_RAPIDFUZZ:
        return _simple_search(parts, query, limit)

    choices = _build_choices(parts)
    choice_texts = [t for t, _ in choices]
    tokens = query.split()

    exact_sets: list[set[int]] = []
    fuzzy_maps: list[dict[int, float]] = []

    def _exact(token: str) -> set[int]:
        tn = _norm_token(token)
        has_letters = bool(re.search(r"[A-Za-zÄÖÜäöüß]", token))
        has_digits  = bool(re.search(r"\d", token))
        is_numeric  = has_digits and not has_letters
        ta = _norm_alnum(token)
        hits: set[int] = set()
        for text, pid in choices:
            normed = _norm_slash(str(text)).lower()
            for cand in _candidate_tokens(normed):
                cn = _norm_token(cand)
                if is_numeric:
                    if cn == tn or (cn.startswith(tn) and not re.search(r"\d", cn[len(tn):])):
                        hits.add(pid); break
                else:  # alnum or pure alpha
                    ca = _norm_alnum(cand)
                    if ca == ta or (ca.startswith(ta) and not re.search(r"\d", ca[len(ta):])):
                        hits.add(pid); break
        return hits

    def _fuzzy(token: str) -> dict[int, float]:
        results = process.extract(
            token, choice_texts,
            scorer=fuzz.WRatio,
            processor=rf_utils.default_process,
            limit=MAX_CANDIDATES,
        )
        best: dict[int, float] = {}
        for _txt, score, idx in results:
            if score < MIN_SCORE:
                continue
            pid = choices[idx][1]
            if score > best.get(pid, 0):
                best[pid] = float(score)
        return best

    for tok in tokens:
        if re.search(r"\d", tok):
            exact_sets.append(_exact(tok))
        else:
            fuzzy_maps.append(_fuzzy(tok))

    # Combine
    if fuzzy_maps:
        if any(not m for m in fuzzy_maps):
            return []
        common = set(fuzzy_maps[0])
        for m in fuzzy_maps[1:]:
            common &= set(m)
        for es in exact_sets:
            common &= es
        if not common:
            return []
        score_map = {
            pid: sum(m[pid] for m in fuzzy_maps) / len(fuzzy_maps)
            for pid in common
        }
    else:
        if not exact_sets:
            return []
        common = set.intersection(*exact_sets) if len(exact_sets) > 1 else exact_sets[0]
        if not common:
            return []
        score_map = {pid: 100.0 for pid in common}

    hits = []
    for p in parts:
        pid = int(p["id"])
        if pid in score_map:
            hits.append({**p, "_score": score_map[pid]})

    hits.sort(key=lambda x: (-x["_score"], x.get("name", "").lower()))
    return hits[:limit]


def _simple_search(parts: list[dict], query: str, limit: int) -> list[dict]:
    """Fallback substring search when rapidfuzz is unavailable."""
    q = query.lower()
    results = []
    for p in parts:
        haystack = " ".join(filter(None, [
            p.get("name"), p.get("article_number"), p.get("supplier"),
            p.get("shelf"), p.get("bin"),
            *p.get("synonyms", []),
            *p.get("manufacturers", []),
        ])).lower()
        if q in haystack:
            results.append(p)
    return results[:limit]
