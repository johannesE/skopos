from __future__ import annotations

import json
import re
from typing import Any

DASHBOARD_MARKER = "<!-- skopos:review-dashboard -->"
REVIEW_MARKER = "<!-- skopos:review -->"
REVIEW_METADATA_PREFIX = "<!-- skopos:review-metadata "
REVIEW_METADATA_RE = re.compile(r"<!--\s*skopos:review-metadata\s+(.*?)\s*-->", re.S)


def norm_login(login: str | None) -> str:
    """Normalize a GitHub login so REST (`name[bot]`) and GraphQL (`name`) forms compare equal."""
    return (login or "").strip().removesuffix("[bot]")


def parse_multi_json(text: str) -> list[Any]:
    text = text.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        pass

    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        parsed_lines: list[Any] = []
        ok = True
        for line in lines:
            try:
                parsed_lines.append(json.loads(line))
            except json.JSONDecodeError:
                ok = False
                break
        if ok:
            flattened: list[Any] = []
            for item in parsed_lines:
                if isinstance(item, list):
                    flattened.extend(item)
                else:
                    flattened.append(item)
            return flattened

    decoder = json.JSONDecoder()
    values: list[Any] = []
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        value, end = decoder.raw_decode(text, idx)
        if isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)
        idx = end
    return values


def normalize_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    text = re.sub(r"`[^`]+`", "`id`", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_issue_headline(body: str) -> str:
    match = re.search(r"\*\*(.*?)\*\*", body or "", re.S)
    if match:
        return normalize_text(match.group(1))
    for line in (body or "").splitlines():
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("_")
            or stripped.startswith("```")
            or stripped.startswith("<!--")
        ):
            continue
        return normalize_text(stripped)
    return ""


def extract_review_metadata(body: str) -> dict[str, str]:
    match = REVIEW_METADATA_RE.search(body or "")
    if not match:
        return {}
    pairs: dict[str, str] = {}
    for token in match.group(1).split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        pairs[key] = value
    return pairs


def token_fingerprint(text: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", normalize_text(text))
        if len(token) >= 4
    }
