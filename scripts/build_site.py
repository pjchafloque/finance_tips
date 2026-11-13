#!/usr/bin/env python3
"""Build site/index.html from data/posts.json, topics.json and transcripts/.

Each post is tagged with topics by keyword (see topics.json), unless
data/topic_overrides.json lists topics for it by hand. Transcripts are plain
text files in transcripts/, named after the reel's code from its link
(transcripts/DfsR8zBy-SD.txt) or its media ID.

Uses only the Python standard library.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "posts.json"
OVERRIDES_PATH = ROOT / "data" / "topic_overrides.json"
TOPICS_PATH = ROOT / "topics.json"
TRANSCRIPTS_DIR = ROOT / "transcripts"
TEMPLATE_PATH = ROOT / "scripts" / "template.html"
OUT_PATH = ROOT / "site" / "index.html"

SPONSORED = re.compile(r"#ad\b|#sponsored\b|#\w*partner\b|\bpaid partnership\b", re.IGNORECASE)
SHORTCODE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:reel|reels|p|tv)/([^/?#]+)")
KINDS = {"REELS": "reel", "IMAGE": "photo", "CAROUSEL_ALBUM": "carousel", "VIDEO": "video"}


def load_json(path: Path, default):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return default


def keyword_pattern(words: list[str], ignore_case: bool) -> re.Pattern | None:
    parts = []
    for word in words:
        word = word.strip()
        if not word:
            continue
        prefix = word.endswith("*")
        core = re.escape(word.rstrip("*"))
        # Only require a word boundary where the keyword starts or ends with a letter or digit.
        start = r"(?<!\w)" if re.match(r"\w", word) else ""
        end = "" if prefix or not re.search(r"\w$", word.rstrip("*")) else r"(?!\w)"
        parts.append(start + core + end)
    if not parts:
        return None
    return re.compile("|".join(parts), re.IGNORECASE if ignore_case else 0)


def compile_topics(topics: list[dict]) -> list[tuple[str, re.Pattern | None, re.Pattern | None]]:
    return [
        (t["id"], keyword_pattern(t.get("keywords", []), True), keyword_pattern(t.get("exact_case", []), False))
        for t in topics
    ]


def shortcode_of(permalink: str) -> str | None:
    match = SHORTCODE.search(permalink or "")
    return match.group(1) if match else None


def read_transcripts() -> dict[str, str]:
    found = {}
    if TRANSCRIPTS_DIR.is_dir():
        for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
            text = path.read_text(encoding="utf-8").strip()
            if text:
                found[path.stem] = text
    return found


def utc_iso(timestamp: str) -> str:
    """Turn Instagram's 2026-11-13T21:20:50+0000 into 2026-11-13T21:20:50Z, which every browser parses."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(timestamp, fmt)
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return timestamp or ""


def build(posts: list[dict], topic_defs: list[dict], overrides: dict, transcripts: dict) -> tuple[list[dict], list[str]]:
    matchers = compile_topics(topic_defs)
    known_topics = {t["id"] for t in topic_defs}
    warnings = []
    used_overrides = set()
    out = []
    for post in posts:
        code = shortcode_of(post.get("permalink", ""))
        caption = post.get("caption") or ""
        transcript = transcripts.get(code or "") or transcripts.get(post["id"]) or ""
        text = f"{caption}\n{transcript}"
        override_key = code if code in overrides else (post["id"] if post["id"] in overrides else None)
        if override_key is not None:
            used_overrides.add(override_key)
            topics = [t for t in overrides[override_key] if t in known_topics]
            for t in overrides[override_key]:
                if t not in known_topics:
                    warnings.append(f"topic_overrides.json: '{t}' (for {override_key}) isn't a topic id in topics.json")
        else:
            topics = [tid for tid, ci, cs in matchers if (ci and ci.search(text)) or (cs and cs.search(text))]
        out.append({
            "id": post["id"],
            "code": code or "",
            "url": post.get("permalink") or "",
            "ts": utc_iso(post.get("timestamp", "")),
            "kind": KINDS.get(post.get("media_product_type")) or KINDS.get(post.get("media_type")) or "post",
            "caption": caption,
            "transcript": transcript,
            "topics": topics,
            "sponsored": bool(SPONSORED.search(caption)),
            "views": post.get("views"),
            "likes": post.get("likes"),
            "stats_at": utc_iso(post.get("stats_at") or ""),
        })
    by_code_or_id = {p["code"] for p in out} | {p["id"] for p in out}
    for key in overrides:
        if key not in by_code_or_id:
            warnings.append(f"topic_overrides.json: no post matches '{key}'")
    for key in transcripts:
        if key not in by_code_or_id:
            warnings.append(f"transcripts/{key}.txt doesn't match any post yet")
    return out, warnings


def render(template: str, payload: dict, title: str) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")  # keep captions from closing the <script> tag
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return template.replace("__TITLE__", safe_title).replace("__SITE_DATA__", blob)


def main() -> int:
    cfg = load_json(CONFIG_PATH, {})
    data = load_json(DATA_PATH, {})
    topic_defs = load_json(TOPICS_PATH, {}).get("topics", [])
    overrides = load_json(OVERRIDES_PATH, {})
    overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
    transcripts = read_transcripts()

    posts, warnings = build(data.get("posts", []), topic_defs, overrides, transcripts)
    payload = {
        "account": data.get("account") or {"username": cfg.get("target_username", "")},
        "checked_at": data.get("checked_at", ""),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "topics": [{"id": t["id"], "label": t["label"]} for t in topic_defs],
        "posts": posts,
    }
    html = render(TEMPLATE_PATH.read_text(encoding="utf-8"), payload, cfg.get("site_title", "Study book"))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")

    reels = [p for p in posts if p["kind"] == "reel"]
    counts = {t["id"]: sum(t["id"] in p["topics"] for p in reels) for t in topic_defs}
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} with {len(posts)} posts ({len(reels)} reels, "
          f"{sum(bool(p['transcript']) for p in posts)} with transcripts).")
    print("Reels per topic: " + ", ".join(f"{k} {v}" for k, v in counts.items())
          + f", not sorted {sum(not p['topics'] for p in reels)}")
    for w in warnings:
        print(f"Note: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
