"""Optional LLM helper for messy menu text. Defaults to keyword matching."""

from __future__ import annotations

import os
import re
from typing import Callable

from provider import MenuItem


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def keyword_match_allergens(
    item: MenuItem, hard_allergens: list[str]
) -> tuple[bool, str]:
    """
    Return (is_safe, reason).
    Safe means no hard allergen appears in tags, allergens, name, or description.
    """
    if not item.allergen_confirmed:
        return False, "allergen status not confirmed"

    haystack = _normalize(
        " ".join(
            [
                item.name,
                item.description,
                " ".join(item.allergens),
                " ".join(item.tags),
            ]
        )
    )

    for allergen in hard_allergens:
        token = _normalize(allergen)
        if token and token in haystack:
            return False, f"contains allergen: {allergen}"

    return True, "keyword match passed"


def keyword_match_no_go(item: MenuItem, no_go: list[str]) -> bool:
    """Return True if item should be excluded for no_go preferences."""
    haystack = _normalize(
        " ".join([item.name, item.description, " ".join(item.tags)])
    )
    for term in no_go:
        token = _normalize(term)
        if token and token in haystack:
            return True
    return False


def keyword_match_cuisine(item: MenuItem, cuisine: str) -> bool:
    return _normalize(item.cuisine) == _normalize(cuisine)


def llm_match_allergens(
    item: MenuItem, hard_allergens: list[str]
) -> tuple[bool, str]:
    """
    Fail-closed LLM path. Keyword check is the floor; the model can only tighten.
    """
    keyword_safe, keyword_reason = keyword_match_allergens(item, hard_allergens)
    if not keyword_safe:
        return False, keyword_reason

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return True, keyword_reason

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return True, keyword_reason

    client = OpenAI(api_key=api_key)
    prompt = (
        "You are a food safety checker. Given a menu item and a list of "
        "allergens the user must avoid, reply with SAFE or UNSAFE and a "
        "short reason.\n\n"
        f"Item name: {item.name}\n"
        f"Description: {item.description}\n"
        f"Listed allergens: {', '.join(item.allergens) or 'none'}\n"
        f"Tags: {', '.join(item.tags) or 'none'}\n"
        f"User allergens: {', '.join(hard_allergens)}\n"
    )

    try:
        response = client.chat.completions.create(
            model=os.environ.get("LUNCH_AGENT_LLM_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=60,
        )
        text = (response.choices[0].message.content or "").strip().upper()
        if text.startswith("SAFE"):
            return True, "llm confirmed safe"
        return False, "llm marked unsafe"
    except Exception:
        return True, keyword_reason


def get_allergen_checker() -> Callable[[MenuItem, list[str]], tuple[bool, str]]:
    """Pick allergen checker based on environment."""
    if os.environ.get("LUNCH_AGENT_USE_LLM", "").lower() in {"1", "true", "yes"}:
        return llm_match_allergens
    return keyword_match_allergens
