from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Any

import yaml

RULES_PATH = Path(__file__).parent.parent / "tagging_rules.yaml"

_COMPILED: dict[str, list[re.Pattern[str]]] | None = None


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    with open(RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _compile_rules() -> tuple[
    list[tuple[str, list[re.Pattern[str]]]],
    list[tuple[str, list[re.Pattern[str]], bool]],
]:
    rules = _load_rules()
    profession: list[tuple[str, list[re.Pattern[str]]]] = []
    for r in rules.get("profession_rules", []):
        patterns = [re.compile(p, re.IGNORECASE) for p in r["patterns"]]
        profession.append((r["tag"], patterns))

    thematic: list[tuple[str, list[re.Pattern[str]], bool]] = []
    for r in rules.get("thematic_rules", []):
        patterns = [re.compile(p, re.IGNORECASE) for p in r["patterns"]]
        thematic.append((r["tag"], patterns, r.get("catch_all", False)))

    return profession, thematic


_PROFESSION_RULES: list[tuple[str, list[re.Pattern[str]]]] | None = None
_THEMATIC_RULES: list[tuple[str, list[re.Pattern[str]], bool]] | None = None


def _ensure_compiled() -> None:
    global _PROFESSION_RULES, _THEMATIC_RULES
    if _PROFESSION_RULES is None:
        _PROFESSION_RULES, _THEMATIC_RULES = _compile_rules()


def tag_article(
    title: str,
    url: str,
    default_tags: list[str],
    default_profession_tags: list[str],
) -> tuple[list[str], list[str]]:
    """Return (thematic_tags, profession_tags) for an article."""
    _ensure_compiled()

    search_text = title  # profession detection on title only
    full_text = f"{title} {url}"  # thematic on title + url

    # Profession tags
    profession_tags: set[str] = set(default_profession_tags)
    for tag, patterns in _PROFESSION_RULES:  # type: ignore[union-attr]
        for pat in patterns:
            if pat.search(search_text):
                profession_tags.add(tag)
                break

    # Thematic tags
    thematic_tags: set[str] = set(default_tags)
    has_specific = False
    catch_all_tag: Optional[str] = None

    for tag, patterns, is_catch_all in _THEMATIC_RULES:  # type: ignore[union-attr]
        if is_catch_all:
            catch_all_tag = tag
            continue
        for pat in patterns:
            if pat.search(full_text):
                thematic_tags.add(tag)
                has_specific = True
                break

    if not has_specific and catch_all_tag:
        thematic_tags.add(catch_all_tag)

    return sorted(thematic_tags), sorted(profession_tags)
