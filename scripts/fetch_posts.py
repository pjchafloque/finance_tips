#!/usr/bin/env python3
"""Pull @your_finance_brother's posts from Instagram's Business Discovery API.

New posts are merged into data/posts.json. Posts already in the file keep
their first_seen date, and their caption is refreshed if it changed.

The first run pages through every post. After that, each run stops as soon
as it reaches a page with nothing new, unless you pass --full.

Needs the IG_ACCESS_TOKEN environment variable: a Page access token for the
Facebook Page linked to the Instagram account whose ID is in config.json.
Uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
DATA_PATH = ROOT / "data" / "posts.json"

MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,timestamp"
ACCOUNT_FIELDS = "name,followers_count,media_count"
# Graph API error codes that usually clear up on their own (temporary errors, rate limits).
RETRYABLE_CODES = {1, 2, 4, 17, 32, 341, 613}
MAX_PAGES = 60


class GraphError(Exception):
    def __init__(self, message: str, code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default):
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    tmp.replace(path)


def http_get_json(url: str) -> dict:
    """GET a Graph API URL and return the parsed JSON.

    Errors come back as GraphError with Meta's message. The URL itself is never
    included in an error, because it carries the access token.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "finance-tips-archive"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        try:
            error = json.load(e).get("error", {})
        except Exception:
            error = {}
        code = error.get("code")
        message = error.get("message") or f"HTTP {e.code}"
        retryable = e.code >= 500 or code in RETRYABLE_CODES or bool(error.get("is_transient"))
        raise GraphError(message, code=code, retryable=retryable) from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", None) or e.__class__.__name__
        raise GraphError(f"Network error: {reason}", retryable=True) from None
    except json.JSONDecodeError:
        raise GraphError("Instagram sent back something that isn't JSON.", retryable=True) from None


def graph_get(version: str, node: str, fields: str, token: str, *, fetch=http_get_json,
              attempts: int = 4, retry_delay: float = 30, log=print) -> dict:
    query = urllib.parse.urlencode({"fields": fields, "access_token": token})
    url = f"https://graph.facebook.com/{version}/{node}?{query}"
    delay = retry_delay
    for attempt in range(1, attempts + 1):
        try:
            return fetch(url)
        except GraphError as e:
            if not e.retryable or attempt == attempts:
                raise
            log(f"Temporary error from Instagram ({e}). Trying again in {delay:g}s.")
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


def discovery_fields(username: str, page_size: int, after: str | None = None) -> str:
    media = f"media.after({after}).limit({page_size})" if after else f"media.limit({page_size})"
    return f"business_discovery.username({username}){{{ACCOUNT_FIELDS},{media}{{{MEDIA_FIELDS}}}}}"


def to_record(item: dict) -> dict:
    return {
        "id": item["id"],
        "permalink": item.get("permalink") or "",
        "timestamp": item.get("timestamp") or "",
        "media_type": item.get("media_type") or "",
        "media_product_type": item.get("media_product_type") or "",
        "caption": item.get("caption") or "",
    }


def run(cfg: dict, token: str, data: dict, *, full_scan: bool = False, fetch=http_get_json,
        retry_delay: float = 30, log=print) -> dict:
    """Fetch posts and merge them into `data` in place. Returns a summary dict.

    If an error stops the run partway, whatever was fetched before it is still
    merged into `data` before the error is raised.
    """
    posts = {p["id"]: p for p in data.get("posts", [])}
    scan_all = full_scan or not data.get("backfill_complete", False)
    page_size = int(cfg.get("page_size", 100))
    stamp = now_iso()
    summary = {"checked": 0, "new_ids": [], "updated": 0, "pages": 0, "reached_end": False}
    after = None
    try:
        for _ in range(MAX_PAGES):
            fields = discovery_fields(cfg["target_username"], page_size, after)
            response = graph_get(cfg["graph_api_version"], cfg["ig_user_id"], fields, token,
                                 fetch=fetch, retry_delay=retry_delay, log=log)
            summary["pages"] += 1
            account = response.get("business_discovery")
            if not account:
                raise GraphError("Instagram returned no business_discovery data. "
                                 "Check target_username and ig_user_id in config.json.")
            data["account"] = {
                "username": cfg["target_username"],
                **{k: account[k] for k in ("name", "followers_count", "media_count") if k in account},
            }
            media = account.get("media") or {}
            items = media.get("data") or []
            new_on_page = 0
            for item in items:
                summary["checked"] += 1
                record = to_record(item)
                existing = posts.get(record["id"])
                if existing is None:
                    record["first_seen"] = stamp
                    posts[record["id"]] = record
                    summary["new_ids"].append(record["id"])
                    new_on_page += 1
                elif any(existing.get(k) != v for k, v in record.items()):
                    existing.update(record)
                    summary["updated"] += 1
            after = ((media.get("paging") or {}).get("cursors") or {}).get("after")
            if not items or not after:
                summary["reached_end"] = True
                break
            if not scan_all and new_on_page == 0:
                break
        else:
            log(f"Stopped after {MAX_PAGES} pages. The next run will continue.")
    finally:
        data["posts"] = sorted(posts.values(), key=lambda p: p.get("timestamp") or "", reverse=True)
        data["checked_at"] = stamp
        if summary["reached_end"]:
            data["backfill_complete"] = True
    return summary


def explain(error: GraphError) -> str:
    if error.code == 190:
        return ("The access token expired or was revoked. Make a new Page token "
                "(README, step 3) and update the IG_ACCESS_TOKEN secret.")
    if error.code in (10, 200):
        return ("The token is missing a permission. Generate it again with instagram_basic, "
                "instagram_manage_insights, pages_read_engagement, pages_show_list and business_management.")
    if error.code == 110:
        return "Instagram couldn't find that username. Check target_username in config.json."
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch new posts into data/posts.json.")
    parser.add_argument("--full", action="store_true",
                        help="page through every post instead of stopping at the first page with nothing new")
    args = parser.parse_args(argv)

    cfg = load_json(CONFIG_PATH, None)
    if not cfg:
        print(f"Missing {CONFIG_PATH.name}.", file=sys.stderr)
        return 2
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("IG_ACCESS_TOKEN isn't set. Add it as a repository secret (README, step 4).", file=sys.stderr)
        return 2

    data = load_json(DATA_PATH, {})
    count_before = len(data.get("posts", []))
    try:
        summary = run(cfg, token, data, full_scan=args.full)
    except GraphError as e:
        if len(data.get("posts", [])) > count_before:
            write_json(DATA_PATH, data)
            print(f"Saved {len(data['posts']) - count_before} new posts before the error.")
        hint = explain(e)
        print(f"Instagram API error: {e}" + (f"\n{hint}" if hint else ""), file=sys.stderr)
        return 1

    write_json(DATA_PATH, data)
    print(f"Checked {summary['checked']} posts on {summary['pages']} page(s): "
          f"{len(summary['new_ids'])} new, {summary['updated']} updated. "
          f"The archive now has {len(data['posts'])} posts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
