#!/usr/bin/env python3
"""scout: search YouTube for one topic and write a ranked research workbook.

Pipeline (mirrors the YouTube Pro app's server/youtube.ts, then goes further):
  search.list          -> relevant video ids (1 of 100 daily search calls per page of 50)
  videos.list          -> stats, duration, status, topics, recording (1 unit per 50)
  channels.list        -> handle, subscribers, country, keywords (1 unit per 50)
  videoCategories.list -> category names (1 unit per run)
  commentThreads.list  -> top comments, only with --comments (1 unit per video)
  yt-dlp               -> hook transcript, vertical, replay heatmap, only with --hooks (no quota)
  local Whisper        -> transcripts from the audio when captions are missing, --transcribe

Sheets: Videos (OWT-Social-Ads layout plus extras), Channels, Summary, and with flags
Comments and Transcripts. Only openpyxl is required beyond the standard library.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from pathlib import Path

BASE_URL = "https://www.googleapis.com/youtube/v3"
TIMEOUT_S = 15
# Key lookup order: $YOUTUBE_API_KEY, then the file named by $SCOUT_ENV_FILE, then
# ~/.config/scout/.env, then ./.env in the working directory.
DEFAULT_ENV_FILES = (
    Path.home() / ".config" / "scout" / ".env",
    Path.cwd() / ".env",
)
SHEET_NAME = "Videos"
CHANNELS_SHEET = "Channels"
COMMENTS_SHEET = "Comments"
TRANSCRIPTS_SHEET = "Transcripts"
SUMMARY_SHEET = "Summary"

VIDEO_PARTS = ("snippet,contentDetails,statistics,status,topicDetails,recordingDetails,"
               "paidProductPlacementDetails,liveStreamingDetails")
CHANNEL_PARTS = "snippet,statistics,topicDetails,brandingSettings"

SHORT_MAX_S = 180          # YouTube Shorts can be up to 3 minutes
DESCRIPTION_CHARS = 300
EXCEL_CELL_MAX = 32000

# yt-dlp probe cache and caption pacing. YouTube's timedtext endpoint returns 429
# after bursts, so fetches are spaced out, retried with backoff, and cached on disk.
CACHE_DIR = Path(os.environ.get("SCOUT_CACHE_DIR", Path.home() / ".cache" / "scout"))
CACHE_TTL_S = 7 * 86400
CAPTION_DELAY_S = float(os.environ.get("SCOUT_CAPTION_DELAY", "1.5"))
CAPTION_BACKOFF_S = (15.0, 45.0)
# Separate video and audio streams merged by ffmpeg. YouTube's single-file mp4 is throttled
# hard and missing for many videos, so it is only the last resort.
DOWNLOAD_FORMAT = os.environ.get(
    "SCOUT_DOWNLOAD_FORMAT",
    "bv*[height<=480][ext=mp4]+ba[ext=m4a]/bv*[height<=480]+ba/b[height<=480]/b")
DOWNLOAD_WORKERS = 3
AUDIO_WORKERS = 4

# Exit codes
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_KEY = 2
EXIT_QUOTA = 3
EXIT_BAD_KEY = 4
EXIT_API = 5
EXIT_FILE = 6

OWT_COLUMNS = [
    "Platform", "Creator", "Handle", "Video ID", "Video Link", "Posted", "Views",
    "Likes", "Comments", "Shares", "Engagement %", "Duration s", "Spark Code",
    "Local File", "Sheet Views", "Ad Status",
]
EXTRA_COLUMNS = [
    # identity and performance
    "Title", "Published", "Relevance #", "Format", "Age d", "Views/day", "Views/Sub",
    "Like %", "Comment %",
    # channel context
    "Channel URL", "Subscribers", "Channel Videos", "Channel Views", "Avg Views/Video",
    "Channel Country", "Channel Created", "Channel Keywords", "Channel Topics",
    # video metadata
    "Category", "Tags", "Tag Count", "Language", "Captions", "HD", "Licensed", "Embeddable",
    "Made for Kids", "Paid Promotion", "AI Disclosure", "License", "Live", "Topics",
    "Blocked Regions", "Description", "Desc Links", "Location", "Thumbnail",
    # --comments
    "Top Comment", "Top Comment Likes", "Comments Off",
    # --hooks
    "Hook", "Vertical", "FPS", "Most Replayed s", "Replay Hotspots", "Chapters",
    "Transcript Words", "Transcript Source",
    # --download
    "Thumbnail File",
]
ALL_COLUMNS = OWT_COLUMNS + EXTRA_COLUMNS

# Columns that are left out of a new workbook when every row is blank. They still
# exist in --into mode so the layout matches OWT-Social-Ads.xlsx exactly.
OPTIONAL_COLUMNS = {
    "Shares", "Spark Code", "Local File", "Sheet Views", "Ad Status", "Thumbnail File",
    "Top Comment", "Top Comment Likes", "Comments Off",
    "Hook", "Vertical", "FPS", "Most Replayed s", "Replay Hotspots", "Chapters",
    "Transcript Words", "Transcript Source",
}

CHANNEL_COLUMNS = [
    "Handle", "Creator", "Channel URL", "Subscribers", "Channel Videos", "Channel Views",
    "Avg Views/Video", "Channel Country", "Channel Created", "Videos in Sample",
    "Sample Views", "Sample Avg Eng %", "Best Video", "Best Video Views", "Best Video Link",
    "Channel Keywords", "Channel Topics",
]
COMMENT_COLUMNS = [
    "Video ID", "Handle", "Title", "Author", "Comment", "Likes", "Replies", "Published",
    "Video Link",
]
TRANSCRIPT_COLUMNS = [
    "Video ID", "Handle", "Title", "Language", "Source", "Transcript Words", "Hook", "Transcript",
    "Video Link",
]

# Widths measured from OWT-Social-Ads.xlsx for A to P, extras chosen to fit.
COLUMN_WIDTHS = {
    "Platform": 9.9, "Creator": 8.9, "Handle": 8.6, "Video ID": 9.6, "Video Link": 11.1,
    "Posted": 8.6, "Views": 7.9, "Likes": 7.4, "Comments": 11.4, "Shares": 8.5,
    "Engagement %": 14.2, "Duration s": 10.9, "Spark Code": 11.9, "Local File": 10.4,
    "Sheet Views": 12.5, "Ad Status": 10.6,
    "Title": 40.0, "Published": 12.0, "Relevance #": 11.0, "Format": 8.0, "Age d": 8.0,
    "Views/day": 11.0, "Views/Sub": 10.0, "Like %": 8.0, "Comment %": 10.0,
    "Channel URL": 28.0, "Subscribers": 12.0, "Channel Videos": 13.0, "Channel Views": 14.0,
    "Avg Views/Video": 15.0, "Channel Country": 14.0, "Channel Created": 14.0,
    "Channel Keywords": 30.0, "Channel Topics": 24.0,
    "Category": 16.0, "Tags": 40.0, "Tag Count": 9.0, "Language": 9.0, "Captions": 9.0,
    "HD": 5.0, "Licensed": 9.0, "Embeddable": 11.0, "Made for Kids": 12.0,
    "Paid Promotion": 14.0, "AI Disclosure": 12.0, "License": 14.0, "Live": 8.0,
    "Topics": 24.0, "Blocked Regions": 14.0, "Description": 50.0, "Desc Links": 10.0,
    "Location": 20.0, "Thumbnail": 24.0,
    "Top Comment": 50.0, "Top Comment Likes": 16.0, "Comments Off": 12.0,
    "Hook": 60.0, "Vertical": 8.0, "FPS": 5.0, "Most Replayed s": 15.0, "Transcript Source": 17.0, "Source": 16.0,
    "Replay Hotspots": 18.0, "Chapters": 9.0, "Transcript Words": 16.0, "Thumbnail File": 24.0,
    "Videos in Sample": 15.0, "Sample Views": 13.0, "Sample Avg Eng %": 16.0,
    "Best Video": 40.0, "Best Video Views": 15.0, "Best Video Link": 28.0,
    "Author": 20.0, "Comment": 70.0, "Replies": 8.0, "Transcript": 100.0,
}
NUMBER_FORMATS = {
    "Views": "#,##0", "Likes": "#,##0", "Comments": "#,##0", "Shares": "#,##0",
    "Subscribers": "#,##0", "Channel Videos": "#,##0", "Channel Views": "#,##0",
    "Avg Views/Video": "#,##0", "Views/day": "#,##0", "Top Comment Likes": "#,##0",
    "Sample Views": "#,##0", "Best Video Views": "#,##0", "Transcript Words": "#,##0",
    "Engagement %": '0.00"%"', "Like %": '0.00"%"', "Comment %": '0.00"%"',
    "Sample Avg Eng %": '0.00"%"', "Views/Sub": "0.00", "Age d": "0.00",
}
HEADER_FILL = "FF233328"
HYPERLINK_KEY = "_hyperlinks"
FONT_KEY = "_fonts"
EXISTING_KEY = "_existing"
META_KEYS = (HYPERLINK_KEY, FONT_KEY, EXISTING_KEY)
LINK_FONT_COLOR = "FF0000FF"
LINK_COLUMNS = {"Video Link", "Channel URL", "Best Video Link", "Thumbnail"}

SINCE_CHOICES = ("any", "hour", "today", "week", "month", "year")
LENGTH_CHOICES = ("any", "short", "medium", "long")
SORT_CHOICES = ("views", "engagement", "likes", "recent", "momentum", "breakout")

URL_RE = re.compile(r"https?://\S+")


class ScoutError(Exception):
    def __init__(self, message: str, code: int = EXIT_API, reason: str = ""):
        super().__init__(message)
        self.code = code
        self.reason = reason


# --------------------------------------------------------------------------- #
# Key loading
# --------------------------------------------------------------------------- #

def parse_env_file(path: Path) -> dict[str, str]:
    """Hand-parse KEY=VALUE lines. Ignores comments, blanks, and `export `."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def env_file_candidates() -> list[Path]:
    override = os.environ.get("SCOUT_ENV_FILE", "").strip()
    files = [Path(override).expanduser()] if override else []
    return files + list(DEFAULT_ENV_FILES)


def load_api_key(env_paths: list[Path] | None = None) -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if key:
        return key
    candidates = env_paths if env_paths is not None else env_file_candidates()
    for path in candidates:
        key = parse_env_file(path).get("YOUTUBE_API_KEY", "").strip()
        if key:
            return key
    looked = ", ".join(str(p) for p in candidates) or "no env files"
    raise ScoutError(
        f"YOUTUBE_API_KEY is not set. Export it, or put it in one of: {looked}. "
        f"SCOUT_ENV_FILE can point at any .env file.",
        EXIT_NO_KEY,
    )


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def classify_error(status: int, body: object) -> ScoutError:
    reason_parts: list[str] = []
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict):
            if isinstance(err.get("message"), str):
                reason_parts.append(err["message"])
            for entry in err.get("errors") or []:
                if isinstance(entry, dict):
                    for k in ("reason", "message"):
                        if isinstance(entry.get(k), str):
                            reason_parts.append(entry[k])
    reason = " ".join(reason_parts)
    low = reason.lower()
    if status == 401 or "keyinvalid" in low or "api key not valid" in low:
        return ScoutError("YouTube rejected the API key. Check YOUTUBE_API_KEY.", EXIT_BAD_KEY, low)
    if status == 429 or "quota" in low or "dailylimit" in low or "rate limit" in low:
        return ScoutError(
            "YouTube quota is exhausted. It resets at midnight Pacific time.", EXIT_QUOTA, low
        )
    if status == 403:
        return ScoutError(f"YouTube refused the request (403): {reason or 'no detail'}", EXIT_API, low)
    return ScoutError(f"YouTube request failed ({status}): {reason or 'no detail'}", EXIT_API, low)


def yt_get(endpoint: str, params: dict, api_key: str, retries: int = 1,
           sleeper=None) -> dict:
    """GET one Data API endpoint. Retries once on 5xx, timeouts, and network errors."""
    sleeper = sleeper or time.sleep
    query = dict(params)
    query["key"] = api_key
    url = f"{BASE_URL}/{endpoint}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = None
            err = classify_error(exc.code, body)
            if exc.code >= 500 and attempt <= retries:
                sleeper(2.0)
                continue
            raise err from None
        except urllib.error.URLError as exc:
            if attempt <= retries:
                sleeper(2.0)
                continue
            raise ScoutError(f"Could not reach YouTube: {exc.reason}", EXIT_API) from None
        except TimeoutError:
            if attempt <= retries:
                sleeper(2.0)
                continue
            raise ScoutError("YouTube did not answer within 15 seconds.", EXIT_API) from None


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #

def published_after(since: str, now: dt.datetime | None = None) -> str | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    if since == "hour":
        cutoff = now - dt.timedelta(hours=1)
    elif since == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif since == "week":
        cutoff = now - dt.timedelta(days=7)
    elif since == "month":
        cutoff = now - dt.timedelta(days=30)
    elif since == "year":
        cutoff = now - dt.timedelta(days=365)
    else:
        return None
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def chunked(items: list, size: int = 50):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --------------------------------------------------------------------------- #
# API calls
# --------------------------------------------------------------------------- #

class Quota:
    """Tracks YouTube Data API usage under the granular quota system (June 2026).

    search.list draws from its own bucket of 100 calls a day; every other read
    method used here costs 1 unit from the shared 10,000 units a day.
    """

    SEARCH_DAILY = 100
    UNITS_DAILY = 10_000

    def __init__(self) -> None:
        self.searches = 0
        self.units = 0

    def summary(self) -> str:
        calls = "call" if self.searches == 1 else "calls"
        return (f"{self.searches} search {calls} of {self.SEARCH_DAILY} a day, "
                f"{self.units} units of {self.UNITS_DAILY:,}")


def search_ids(topic: str, max_results: int, since: str, length: str,
               api_key: str, quota: Quota) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    while len(ids) < max_results:
        params = {
            "part": "snippet",
            "q": topic,
            "type": "video",
            "order": "relevance",
            "maxResults": str(min(50, max_results - len(ids))),
        }
        after = published_after(since)
        if after:
            params["publishedAfter"] = after
        if length != "any":
            params["videoDuration"] = length
        if page_token:
            params["pageToken"] = page_token
        data = yt_get("search", params, api_key)
        quota.searches += 1
        for item in data.get("items", []):
            vid = (item.get("id") or {}).get("videoId")
            if vid and vid not in seen:
                seen.add(vid)
                ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token or not data.get("items"):
            break
    return ids[:max_results]


def fetch_videos(ids: list[str], api_key: str, quota: Quota) -> list[dict]:
    videos: list[dict] = []
    for batch in chunked(ids):
        data = yt_get("videos", {
            "part": VIDEO_PARTS,
            "id": ",".join(batch),
            "maxResults": "50",
        }, api_key)
        quota.units += 1
        videos.extend(data.get("items", []))
    return videos


def fetch_channels(channel_ids: list[str], api_key: str, quota: Quota) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for batch in chunked(channel_ids):
        data = yt_get("channels", {
            "part": CHANNEL_PARTS,
            "id": ",".join(batch),
            "maxResults": "50",
        }, api_key)
        quota.units += 1
        for ch in data.get("items", []):
            out[ch.get("id", "")] = ch
    return out


def fetch_categories(api_key: str, quota: Quota, region: str = "US") -> dict[str, str]:
    data = yt_get("videoCategories", {"part": "snippet", "regionCode": region}, api_key)
    quota.units += 1
    return {
        item.get("id", ""): (item.get("snippet") or {}).get("title", "")
        for item in data.get("items", [])
    }


def fetch_comments(video_id: str, limit: int, api_key: str, quota: Quota) -> tuple[list[dict], bool]:
    """Return (comments, disabled). Raises on quota or key errors only."""
    try:
        data = yt_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": str(max(1, min(100, limit))),
            "textFormat": "plainText",
        }, api_key)
    except ScoutError as exc:
        if exc.code in (EXIT_QUOTA, EXIT_BAD_KEY):
            raise
        if "commentsdisabled" in exc.reason or "disabled comments" in exc.reason:
            return [], True
        raise
    quota.units += 1
    out: list[dict] = []
    for thread in data.get("items", []):
        snip = (thread.get("snippet") or {})
        top = ((snip.get("topLevelComment") or {}).get("snippet") or {})
        out.append({
            "Author": top.get("authorDisplayName") or "",
            "Comment": (top.get("textOriginal") or top.get("textDisplay") or "").strip(),
            "Likes": to_int(top.get("likeCount")) or 0,
            "Replies": to_int(snip.get("totalReplyCount")) or 0,
            "Published": (top.get("publishedAt") or "")[:10],
        })
    return out, False


# --------------------------------------------------------------------------- #
# yt-dlp probe (no quota): hook transcript, vertical, heatmap
# --------------------------------------------------------------------------- #

def pick_caption_url(info: dict) -> tuple[str, str]:
    """Return (language, json3 url) preferring manual subs, then auto captions."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    preferred: list[str] = []
    lang = (info.get("language") or "").strip()
    if lang:
        preferred += [lang, lang.split("-")[0]]
    preferred += ["en", "en-orig", "en-US", "en-GB"]

    def find(tracks: dict, keys: list[str]) -> tuple[str, str]:
        for key in keys:
            for fmt in tracks.get(key) or []:
                if fmt.get("ext") == "json3" and fmt.get("url"):
                    return key, fmt["url"]
        return "", ""

    for tracks in (manual, auto):
        found = find(tracks, preferred)
        if found[1]:
            return found
        # any english-ish key
        found = find(tracks, [k for k in tracks if k.lower().startswith("en")])
        if found[1]:
            return found
    # last resort: original-language auto captions
    for key, fmts in auto.items():
        if key.endswith("-orig"):
            for fmt in fmts:
                if fmt.get("ext") == "json3" and fmt.get("url"):
                    return key, fmt["url"]
    return "", ""


def parse_json3(data: dict, hook_seconds: float) -> tuple[str, str]:
    """Return (hook_text, full_text) from a json3 caption payload."""
    hook: list[str] = []
    full: list[str] = []
    for event in data.get("events") or []:
        segs = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        full.append(text)
        if (event.get("tStartMs") or 0) < hook_seconds * 1000:
            hook.append(text)
    return " ".join(hook).strip(), " ".join(full).strip()


def heatmap_hotspots(heatmap: list | None, skip_first_s: float = 2.0,
                     min_gap_s: float = 5.0, limit: int = 3) -> list[int]:
    """Return start seconds of the strongest replay peaks, best first.

    YouTube's "most replayed" curve always starts at 1.0 and decays, so the
    opening is ignored and only local maxima (a segment higher than both
    neighbours) count as peaks. Peaks closer than min_gap_s are merged.
    """
    segs = [s for s in (heatmap or []) if isinstance(s, dict)]
    segs.sort(key=lambda s: s.get("start_time") or 0)
    if len(segs) < 3:
        return []
    values = [float(s.get("value") or 0) for s in segs]
    starts = [float(s.get("start_time") or 0) for s in segs]
    peaks = [
        (values[i], starts[i]) for i in range(1, len(segs) - 1)
        if starts[i] >= skip_first_s and values[i] > values[i - 1] and values[i] >= values[i + 1]
    ]
    peaks.sort(key=lambda p: p[0], reverse=True)
    picked: list[int] = []
    for _, start in peaks:
        start_i = int(round(start))
        if all(abs(start_i - p) >= min_gap_s for p in picked):
            picked.append(start_i)
        if len(picked) >= limit:
            break
    return picked


class RateLimited(Exception):
    """The caption endpoint answered 429."""


INFO_KEYS = ("id", "width", "height", "fps", "language", "duration", "chapters", "heatmap")


def _cache_path(video_id: str, cache_dir: Path | None) -> Path | None:
    if cache_dir is None or not video_id:
        return None
    return cache_dir / f"{video_id}.json"


def cache_read(video_id: str, cache_dir: Path | None) -> dict | None:
    path = _cache_path(video_id, cache_dir)
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - float(data.get("saved_at") or 0) > CACHE_TTL_S:
        return None
    return data


def cache_write(video_id: str, cache_dir: Path | None, data: dict) -> None:
    path = _cache_path(video_id, cache_dir)
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data["saved_at"] = time.time()
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def video_id_from_url(url: str) -> str:
    m = re.search(r"[?&]v=([\w-]{6,})", url or "")
    return m.group(1) if m else ""


def probe_video(video_url: str, hook_seconds: float = 15.0,
                runner=None, fetcher=None, cache_dir: Path | None = None,
                sleeper=None, fetch_captions: bool = True) -> dict:
    """Ask yt-dlp for metadata and captions. Never raises; returns {} on failure.

    Results are cached per video id under cache_dir. When the caption endpoint
    rate-limits, the dict carries "_rate_limited": True so callers can report it.
    With fetch_captions=False only cached captions are used (circuit breaker).
    """
    runner = runner or _run_ytdlp_json
    fetcher = fetcher or _fetch_json
    sleeper = sleeper or time.sleep
    vid = video_id_from_url(video_url)
    cached = cache_read(vid, cache_dir) or {}
    info = cached.get("info")
    if not info:
        full_info = runner(video_url)
        if not full_info:
            return {}
        info = {k: full_info.get(k) for k in INFO_KEYS}
        lang, url = pick_caption_url(full_info)
        info["caption_lang"], info["caption_url"] = lang, url
        cached = {"info": info}
        cache_write(vid, cache_dir, cached)

    out: dict = {}
    width, height = info.get("width"), info.get("height")
    if width and height:
        out["Vertical"] = "yes" if height > width else "no"
    if info.get("fps"):
        out["FPS"] = int(round(info["fps"]))
    spots = heatmap_hotspots(info.get("heatmap"))
    if spots:
        out["Most Replayed s"] = spots[0]
        out["Replay Hotspots"] = ", ".join(f"{s}s" for s in spots)
    chapters = info.get("chapters")
    out["Chapters"] = len(chapters) if isinstance(chapters, list) else 0

    captions = cached.get("captions")
    url = info.get("caption_url")
    if captions is None and url and not fetch_captions:
        out["_rate_limited"] = True
    elif captions is None and url:
        for attempt, delay in enumerate((0.0,) + CAPTION_BACKOFF_S):
            if delay:
                sleeper(delay)
            try:
                captions = fetcher(url)
                break
            except RateLimited:
                if attempt == len(CAPTION_BACKOFF_S):
                    out["_rate_limited"] = True
        if captions is not None:
            cached["captions"] = captions
            cache_write(vid, cache_dir, cached)
    if captions:
        hook, full = parse_json3(captions, hook_seconds)
        out["Hook"] = hook
        out["Transcript"] = full
        out["Transcript Words"] = len(full.split())
        out["Language"] = info.get("caption_lang") or ""
    return out


def _run_ytdlp_json(video_url: str) -> dict | None:
    cmd = ["yt-dlp", "-j", "--no-warnings", "--no-playlist", video_url]
    try:
        proc = subprocess.run(cmd, check=True, timeout=90, capture_output=True)
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError,
            json.JSONDecodeError):
        return None


def _fetch_json(url: str) -> dict | None:
    """Fetch caption JSON. Raises RateLimited on 429, returns None on other failures."""
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited() from None
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Row building
# --------------------------------------------------------------------------- #

ISO_DURATION = re.compile(
    r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


def parse_iso_duration(value: str | None) -> float | None:
    if not value:
        return None
    m = ISO_DURATION.match(value)
    if not m:
        return None
    d = int(m.group("d") or 0)
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_epoch(published_at: str | None) -> float | None:
    if not published_at:
        return None
    try:
        ts = dt.datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            ts = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return float(int(ts.timestamp()))


def pct(numerator: int | None, views: int | None) -> float:
    if not views:
        return 0.0
    return round((numerator or 0) / views * 100, 2)


def engagement_pct(views: int | None, likes: int | None, comments: int | None) -> float:
    return pct((likes or 0) + (comments or 0), views)


def yes_no(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes"):
            return "yes"
        if low in ("false", "no"):
            return "no"
        return ""
    return "yes" if value else "no"


def handle_from_channel(channel: dict | None) -> str:
    if not channel:
        return ""
    custom = ((channel.get("snippet") or {}).get("customUrl") or "").strip()
    return custom[1:] if custom.startswith("@") else custom


def pick_thumbnail(snippet: dict) -> str:
    thumbs = snippet.get("thumbnails") or {}
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbs.get(key) or {}).get("url")
        if url:
            return url
    return ""


def topic_names(urls: list | None) -> str:
    names: list[str] = []
    for url in urls or []:
        tail = urllib.parse.unquote(str(url).rstrip("/").rsplit("/", 1)[-1])
        name = tail.replace("_", " ").strip()
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def region_summary(details: dict) -> str:
    rr = details.get("regionRestriction") or {}
    blocked = rr.get("blocked") or []
    allowed = rr.get("allowed") or []
    if blocked:
        return f"{len(blocked)} blocked"
    if allowed:
        return f"only {len(allowed)} allowed"
    return ""


def location_summary(recording: dict | None) -> str:
    if not recording:
        return ""
    desc = (recording.get("locationDescription") or "").strip()
    loc = recording.get("location") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if desc:
        return desc
    if lat is not None and lon is not None:
        return f"{lat:.4f},{lon:.4f}"
    return ""


def video_format(duration_s: float | None, live: bool, vertical: str = "") -> str:
    if live:
        return "Live"
    if duration_s is not None and duration_s <= SHORT_MAX_S and vertical != "no":
        return "Short"
    return "Video"


def age_days(posted: float | None, now: float | None = None) -> float | None:
    if posted is None:
        return None
    now = now if now is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    return round(max((now - posted) / 86400.0, 0.25), 2)


def build_rows(videos: list[dict], channels: dict[str, dict],
               categories: dict[str, str] | None = None,
               relevance: dict[str, int] | None = None,
               now: float | None = None) -> list[dict]:
    categories = categories or {}
    relevance = relevance or {}
    rows: list[dict] = []
    for v in videos:
        vid = v.get("id") or ""
        snippet = v.get("snippet") or {}
        stats = v.get("statistics") or {}
        details = v.get("contentDetails") or {}
        status = v.get("status") or {}
        topics = v.get("topicDetails") or {}
        recording = v.get("recordingDetails") or {}
        paid = v.get("paidProductPlacementDetails") or {}
        live_details = v.get("liveStreamingDetails") or {}
        channel_id = snippet.get("channelId") or ""
        channel = channels.get(channel_id)
        ch_snip = (channel or {}).get("snippet") or {}
        ch_stats = (channel or {}).get("statistics") or {}
        ch_brand = ((channel or {}).get("brandingSettings") or {}).get("channel") or {}
        ch_topics = (channel or {}).get("topicDetails") or {}

        views = to_int(stats.get("viewCount"))
        likes = to_int(stats.get("likeCount"))
        comments = to_int(stats.get("commentCount"))
        subs = None
        if channel and not ch_stats.get("hiddenSubscriberCount"):
            subs = to_int(ch_stats.get("subscriberCount"))
        ch_videos = to_int(ch_stats.get("videoCount"))
        ch_views = to_int(ch_stats.get("viewCount"))
        handle = handle_from_channel(channel)
        channel_url = (
            f"https://www.youtube.com/@{handle}" if handle
            else f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
        )
        posted = to_epoch(snippet.get("publishedAt"))
        duration_s = parse_iso_duration(details.get("duration"))
        age = age_days(posted, now)
        description = snippet.get("description") or ""
        tags = [t for t in (snippet.get("tags") or []) if isinstance(t, str)]
        live_flag = snippet.get("liveBroadcastContent") or "none"
        was_live = bool(live_details)
        live_label = "" if live_flag == "none" and not was_live else (
            live_flag if live_flag != "none" else "was live")

        rows.append({
            "Platform": "YouTube",
            "Creator": snippet.get("channelTitle") or "",
            "Handle": handle,
            "Video ID": vid,
            "Video Link": f"https://www.youtube.com/watch?v={vid}",
            "Posted": posted,
            "Views": views,
            "Likes": likes,
            "Comments": comments,
            "Shares": None,
            "Engagement %": engagement_pct(views, likes, comments),
            "Duration s": duration_s,
            "Spark Code": None,
            "Local File": None,
            "Sheet Views": None,
            "Ad Status": None,
            "Title": snippet.get("title") or "",
            "Published": (snippet.get("publishedAt") or "")[:10],
            "Relevance #": relevance.get(vid),
            "Format": video_format(duration_s, was_live or live_flag == "live"),
            "Age d": age,
            "Views/day": int(round(views / age)) if views is not None and age else None,
            "Views/Sub": round(views / subs, 2) if views is not None and subs else None,
            "Like %": pct(likes, views),
            "Comment %": pct(comments, views),
            "Channel URL": channel_url,
            "Subscribers": subs,
            "Channel Videos": ch_videos,
            "Channel Views": ch_views,
            "Avg Views/Video": int(round(ch_views / ch_videos)) if ch_views and ch_videos else None,
            "Channel Country": ch_snip.get("country") or ch_brand.get("country") or "",
            "Channel Created": (ch_snip.get("publishedAt") or "")[:10],
            "Channel Keywords": (ch_brand.get("keywords") or "")[:500],
            "Channel Topics": topic_names(ch_topics.get("topicCategories")),
            "Category": categories.get(str(snippet.get("categoryId") or ""), "")
            or (str(snippet.get("categoryId")) if snippet.get("categoryId") else ""),
            "Tags": ", ".join(tags)[:2000],
            "Tag Count": len(tags),
            "Language": snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or "",
            "Captions": yes_no(details.get("caption")),
            "HD": yes_no((details.get("definition") or "") == "hd") if details.get("definition") else "",
            "Licensed": yes_no(details.get("licensedContent")),
            "Embeddable": yes_no(status.get("embeddable")),
            "Made for Kids": yes_no(status.get("madeForKids")),
            "Paid Promotion": yes_no(paid.get("hasPaidProductPlacement")),
            "AI Disclosure": yes_no(status.get("containsSyntheticMedia")),
            "License": status.get("license") or "",
            "Live": live_label,
            "Topics": topic_names(topics.get("topicCategories")),
            "Blocked Regions": region_summary(details),
            "Description": re.sub(r"\s+", " ", description)[:DESCRIPTION_CHARS],
            "Desc Links": len(URL_RE.findall(description)),
            "Location": location_summary(recording),
            "Thumbnail": pick_thumbnail(snippet),
            "Top Comment": None,
            "Top Comment Likes": None,
            "Comments Off": None,
            "Hook": None,
            "Vertical": None,
            "FPS": None,
            "Most Replayed s": None,
            "Replay Hotspots": None,
            "Chapters": None,
            "Transcript Words": None,
            "Transcript Source": None,
            "Thumbnail File": None,
        })
    return rows


def sort_key(sort: str):
    if sort == "engagement":
        return lambda r: (_num(r.get("Engagement %")), _num(r.get("Views")))
    if sort == "likes":
        return lambda r: (_num(r.get("Likes")), _num(r.get("Views")))
    if sort == "recent":
        return lambda r: (_num(r.get("Posted")), _num(r.get("Views")))
    if sort == "momentum":
        return lambda r: (_num(r.get("Views/day")), _num(r.get("Views")))
    if sort == "breakout":
        return lambda r: (_num(r.get("Views/Sub")), _num(r.get("Views")))
    return lambda r: (_num(r.get("Views")), _num(r.get("Likes")))


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sort_rows(rows: list[dict], sort: str) -> list[dict]:
    return sorted(rows, key=sort_key(sort), reverse=True)


# --------------------------------------------------------------------------- #
# Enrichment: comments, hooks, downloads
# --------------------------------------------------------------------------- #

def enrich_comments(rows: list[dict], limit: int, api_key: str, quota: Quota,
                    progress=None) -> tuple[list[dict], list[str]]:
    comment_rows: list[dict] = []
    warnings: list[str] = []
    for i, row in enumerate(rows, start=1):
        try:
            comments, disabled = fetch_comments(row["Video ID"], limit, api_key, quota)
        except ScoutError as exc:
            if exc.code in (EXIT_QUOTA, EXIT_BAD_KEY):
                raise
            warnings.append(f"{row['Video ID']}: comments failed: {exc}")
            continue
        row["Comments Off"] = "yes" if disabled else "no"
        if comments:
            top = max(comments, key=lambda c: c["Likes"])
            row["Top Comment"] = top["Comment"][:1000]
            row["Top Comment Likes"] = top["Likes"]
        for c in comments:
            comment_rows.append({
                "Video ID": row["Video ID"],
                "Handle": row["Handle"],
                "Title": row["Title"],
                **c,
                "Video Link": row["Video Link"],
            })
        if progress and i % 10 == 0:
            progress(f"comments {i}/{len(rows)}")
    return comment_rows, warnings


def enrich_hooks(rows: list[dict], hook_seconds: float, progress=None,
                 prober=None, cache_dir: Path | None = None,
                 delay_s: float = CAPTION_DELAY_S, sleeper=None,
                 transcribe_after: bool = False) -> tuple[list[dict], list[str]]:
    prober = prober or (lambda url, s, fetch=True: probe_video(
        url, s, cache_dir=cache_dir, fetch_captions=fetch))
    sleeper = sleeper or time.sleep
    transcript_rows: list[dict] = []
    warnings: list[str] = []
    rate_limited = 0
    captions_open = True   # flips off after one full backoff failure
    for i, row in enumerate(rows, start=1):
        if i > 1 and delay_s and captions_open:
            sleeper(delay_s)
        info = prober(row["Video Link"], hook_seconds, captions_open)
        if not info:
            warnings.append(f"{row['Video ID']}: yt-dlp probe failed")
            continue
        if info.get("_rate_limited"):
            rate_limited += 1
            if captions_open and progress:
                progress("captions rate-limited (HTTP 429); skipping caption fetches for the "
                         "rest of this run, metadata still collected")
            captions_open = False
        for key in ("Hook", "Vertical", "FPS", "Most Replayed s", "Replay Hotspots",
                    "Chapters", "Transcript Words"):
            if key in info:
                row[key] = info[key]
        if info.get("Language") and not row.get("Language"):
            row["Language"] = info["Language"]
        if row.get("Vertical") == "no" and row.get("Format") == "Short":
            row["Format"] = "Video"
        if info.get("Transcript"):
            row["Transcript Source"] = "captions"
            transcript_rows.append({
                "Video ID": row["Video ID"],
                "Handle": row["Handle"],
                "Title": row["Title"],
                "Language": info.get("Language", ""),
                "Source": "captions",
                "Transcript Words": info.get("Transcript Words"),
                "Hook": info.get("Hook", ""),
                "Transcript": info["Transcript"][:EXCEL_CELL_MAX],
                "Video Link": row["Video Link"],
            })
        if progress and i % 5 == 0:
            progress(f"hooks {i}/{len(rows)}")
    if rate_limited and transcribe_after:
        warnings.append(
            f"captions rate-limited by YouTube for {rate_limited} videos (HTTP 429); "
            f"--transcribe fills them locally, see the Transcript Source column.")
    elif rate_limited:
        warnings.append(
            f"captions rate-limited by YouTube for {rate_limited} videos (HTTP 429). "
            f"The block can last hours. Add --transcribe to fill them locally with Whisper, or "
            f"rerun later; cached results are reused so only the missing captions are fetched.")
    return transcript_rows, warnings


# --------------------------------------------------------------------------- #
# Local transcription (--transcribe): no YouTube caption requests at all
# --------------------------------------------------------------------------- #

HOOK_WORDS_WINDOW_S = 120.0


# Rough GPU memory each OpenAI whisper model needs, in GiB, including working memory.
WHISPER_GPU_GIB = {"tiny": 1.0, "base": 1.2, "small": 2.0, "medium": 5.0, "turbo": 6.0,
                   "large": 10.0, "large-v3": 10.0}


def fit_whisper_model(requested: str, free_gib: float) -> str | None:
    """Largest model, starting from the requested one, that fits in the free GPU memory."""
    ladder = [requested] + [m for m in ("small", "base", "tiny")
                            if WHISPER_GPU_GIB[m] < WHISPER_GPU_GIB.get(requested, 6.0)]
    for name in ladder:
        if WHISPER_GPU_GIB.get(name, 6.0) <= free_gib * 0.9:
            return name
    return None


def _is_oom(exc: Exception) -> bool:
    return "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"


class Transcriber:
    """Local speech-to-text. OpenAI whisper on CUDA, sized to the free GPU memory; else
    faster-whisper on CPU (int8); else OpenAI whisper on CPU. Loaded lazily on first use,
    and moved to the CPU if the GPU runs out of memory mid-run."""

    def __init__(self, model: str = "turbo") -> None:
        self.model = model
        self.backend = ""
        self._kind = ""
        self._m = None

    def _load(self) -> None:
        if self._m is not None:
            return
        errors: list[str] = []
        try:
            import torch
            import whisper
            if torch.cuda.is_available():
                free_gib = torch.cuda.mem_get_info()[0] / 2**30
                name = fit_whisper_model(self.model, free_gib)
                if name:
                    self._m = whisper.load_model(name, device="cuda")
                    self._kind, self.backend = "openai", f"whisper {name} (gpu)"
                    return
                errors.append(f"gpu: only {free_gib:.1f} GiB free")
        except Exception as exc:  # noqa: BLE001 - try the next backend
            errors.append(f"whisper: {type(exc).__name__}")
        self._load_cpu(errors)

    def _load_cpu(self, errors: list[str] | None = None) -> None:
        errors = errors if errors is not None else []
        name = {"turbo": "small", "large": "small", "large-v3": "small"}.get(self.model, self.model)
        try:
            from faster_whisper import WhisperModel
            self._m = WhisperModel(name, device="cpu", compute_type="int8")
            self._kind, self.backend = "faster", f"faster-whisper {name} (cpu)"
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"faster-whisper: {type(exc).__name__}")
        try:
            import whisper
            self._m = whisper.load_model(name, device="cpu")
            self._kind, self.backend = "openai-cpu", f"whisper {name} (cpu)"
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"whisper cpu: {type(exc).__name__}")
        raise ScoutError(
            "No local speech-to-text available for --transcribe. Install openai-whisper "
            "(GPU) or faster-whisper (CPU). Tried: " + ", ".join(errors), EXIT_FILE)

    def _fallback_to_cpu(self) -> None:
        self._m = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        self._load_cpu()

    def __call__(self, path: Path) -> dict:
        self._load()
        try:
            return self._transcribe(path)
        except Exception as exc:  # noqa: BLE001
            if self._kind == "openai" and _is_oom(exc):
                self._fallback_to_cpu()
                return self._transcribe(path)
            raise

    def _transcribe(self, path: Path) -> dict:
        if self._kind == "faster":
            segs, info = self._m.transcribe(str(path), vad_filter=True, word_timestamps=True)
            segs = list(segs)
            segments = [[round(s.start, 2), round(s.end, 2), s.text.strip()] for s in segs]
            words = [[round(w.start, 2), w.word] for s in segs for w in (s.words or [])]
            language = info.language or ""
        else:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = self._m.transcribe(str(path), word_timestamps=True,
                                       fp16=self._kind == "openai", verbose=None)
            segments = [[round(s["start"], 2), round(s["end"], 2), s["text"].strip()]
                        for s in r.get("segments", [])]
            words = [[round(w["start"], 2), w["word"]]
                     for s in r.get("segments", []) for w in s.get("words", [])]
            language = r.get("language") or ""
        return {
            "backend": self.backend,
            "language": language,
            "segments": segments,
            "words": [w for w in words if w[0] < HOOK_WORDS_WINDOW_S],
        }


def hook_from_transcript(result: dict, hook_seconds: float) -> str:
    words = result.get("words") or []
    if words:
        text = "".join(w[1] for w in words if w[0] < hook_seconds)
    else:
        text = " ".join(s[2] for s in result.get("segments", []) if s[0] < hook_seconds)
    return re.sub(r"\s+", " ", text).strip()


def fetch_audio(video_url: str, video_id: str, out_dir: Path, runner=None,
                timeout: float = 900) -> Path | None:
    """Download audio only (no captions endpoint involved). Returns the file or None."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(f for f in out_dir.glob(f"{video_id}.*") if f.suffix not in (".part", ".ytdl"))
    if existing:
        return existing[0]
    cmd = ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist", "--quiet",
           "--no-warnings", "-o", str(out_dir / f"{video_id}.%(ext)s"), video_url]
    run = runner or (lambda c: subprocess.run(c, check=True, timeout=timeout,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
    try:
        run(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None
    found = sorted(f for f in out_dir.glob(f"{video_id}.*") if f.suffix not in (".part", ".ytdl"))
    return found[0] if found else None


def enrich_transcribe(rows: list[dict], hook_seconds: float, transcriber, *,
                      media_dir: Path | None = None, cache_dir: Path | None = None,
                      audio_fetcher=None, progress=None) -> tuple[list[dict], list[str]]:
    """Fill Hook, Transcript Words, and a Transcripts row for every video that has no
    caption transcript yet, by transcribing its audio locally. Audio for videos without a
    local file is fetched a few at a time in the background while transcription runs."""
    todo = [r for r in rows if not r.get("Transcript Words")]
    transcript_rows: list[dict] = []
    warnings: list[str] = []
    audio_dir = (cache_dir or CACHE_DIR) / "audio"
    fetch = audio_fetcher or (lambda row: fetch_audio(
        row["Video Link"], row["Video ID"], audio_dir, timeout=_media_timeout(row, 900)))

    def local_media(row: dict) -> Path | None:
        if media_dir and row.get("Local File"):
            candidate = media_dir / str(row["Local File"])
            return candidate if candidate.exists() else None
        return None

    need_audio = [r for r in todo if not (cache_read(r["Video ID"], cache_dir) or {}).get("whisper")
                  and local_media(r) is None]
    pool = ThreadPoolExecutor(max_workers=AUDIO_WORKERS)
    pending = {r["Video ID"]: pool.submit(fetch, r) for r in need_audio}
    try:
        for i, row in enumerate(todo, start=1):
            vid = row["Video ID"]
            cached = cache_read(vid, cache_dir) or {}
            result = cached.get("whisper")
            if not result:
                media = local_media(row)
                if media is None and vid in pending:
                    try:
                        media = pending[vid].result()
                    except Exception:  # noqa: BLE001 - a failed fetch is reported below
                        media = None
                if not media:
                    warnings.append(f"{vid}: no audio available to transcribe")
                    continue
                try:
                    result = transcriber(media)
                except ScoutError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad file should not stop the run
                    # A local video can lack an audio track; fetch the audio and try once more.
                    retry = fetch(row) if media == local_media(row) else None
                    try:
                        if not retry:
                            raise exc
                        result = transcriber(retry)
                    except ScoutError:
                        raise
                    except Exception as exc2:  # noqa: BLE001
                        warnings.append(f"{vid}: transcription failed ({type(exc2).__name__})")
                        continue
                cached["whisper"] = result
                cache_write(vid, cache_dir, cached)
            full = " ".join(seg[2] for seg in result.get("segments", [])).strip()
            if not full:
                row["Transcript Source"] = "no speech"
                continue
            hook = hook_from_transcript(result, hook_seconds)
            row["Hook"] = hook
            row["Transcript Words"] = len(full.split())
            row["Transcript Source"] = "whisper"
            if result.get("language") and not row.get("Language"):
                row["Language"] = result["language"]
            transcript_rows.append({
                "Video ID": vid,
                "Handle": row.get("Handle"),
                "Title": row.get("Title"),
                "Language": result.get("language", ""),
                "Source": f"whisper ({result.get('backend', '')})".replace(" ()", ""),
                "Transcript Words": row["Transcript Words"],
                "Hook": hook,
                "Transcript": full[:EXCEL_CELL_MAX],
                "Video Link": row.get("Video Link"),
            })
            if progress and i % 5 == 0:
                progress(f"transcribed {i}/{len(todo)}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return transcript_rows, warnings


def _media_timeout(row: dict, floor: float) -> float:
    """Allow long videos more time than short ones."""
    try:
        return max(floor, float(row.get("Duration s") or 0) * 1.5)
    except (TypeError, ValueError):
        return floor


def _download_video(row: dict, out_dir: Path) -> tuple[str | None, str | None]:
    """Download one video. Returns (local file name, warning)."""
    vid = row["Video ID"]
    stem = f"{row.get('Handle') or 'youtube'}_{vid}"
    target = out_dir / f"{stem}.mp4"
    if target.exists():
        return target.name, None
    cmd = [
        "yt-dlp", "-f", DOWNLOAD_FORMAT, "--merge-output-format", "mp4", "--no-playlist",
        "--quiet", "--no-warnings", "-o", str(out_dir / f"{stem}.%(ext)s"), row["Video Link"],
    ]
    try:
        subprocess.run(cmd, check=True, timeout=_media_timeout(row, 600),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None, "yt-dlp is not installed; skipped downloads."
    except subprocess.TimeoutExpired:
        return None, f"{vid}: download timed out"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return None, f"{vid}: {detail[-1] if detail else 'download failed'}"
    found = sorted(f for f in out_dir.glob(f"{stem}.*")
                   if f.suffix not in (".jpg", ".part", ".ytdl"))
    return (found[0].name, None) if found else (None, f"{vid}: download produced no file")


def download_videos(rows: list[dict], out_dir: Path, video_limit: int | None = None) -> list[str]:
    """Save thumbnails for every row and videos for the first `video_limit` rows (all when None).

    Thumbnails are small and fetched one by one; videos download a few at a time.
    """
    warnings: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    limit = len(rows) if not video_limit or video_limit < 0 else video_limit
    for row in rows:
        thumb_url = row.get("Thumbnail") or ""
        if thumb_url:
            thumb_path = out_dir / f"{row.get('Handle') or 'youtube'}_{row['Video ID']}.jpg"
            if (thumb_path.exists() or _download_file(thumb_url, thumb_path)
                    or _download_file(thumb_url, thumb_path)):
                row["Thumbnail File"] = thumb_path.name
            else:
                warnings.append(f"{row['Video ID']}: thumbnail download failed")
    targets = rows[:limit]
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        results = list(pool.map(lambda r: _download_video(r, out_dir), targets))
    for row, (name, warning) in zip(targets, results, strict=True):
        if name:
            row["Local File"] = name
        if warning and warning not in warnings:
            warnings.append(warning)
    return warnings


def _download_file(url: str, path: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            path.write_bytes(resp.read())
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Channels and Summary
# --------------------------------------------------------------------------- #

def build_channel_rows(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        key = r.get("Channel URL") or r.get("Creator") or ""
        groups.setdefault(key, []).append(r)
    out: list[dict] = []
    for vids in groups.values():
        first = vids[0]
        best = max(vids, key=lambda r: _num(r.get("Views")))
        sample_views = sum(int(_num(r.get("Views"))) for r in vids)
        eng = [_num(r.get("Engagement %")) for r in vids]
        out.append({
            "Handle": first.get("Handle"),
            "Creator": first.get("Creator"),
            "Channel URL": first.get("Channel URL"),
            "Subscribers": first.get("Subscribers"),
            "Channel Videos": first.get("Channel Videos"),
            "Channel Views": first.get("Channel Views"),
            "Avg Views/Video": first.get("Avg Views/Video"),
            "Channel Country": first.get("Channel Country"),
            "Channel Created": first.get("Channel Created"),
            "Videos in Sample": len(vids),
            "Sample Views": sample_views,
            "Sample Avg Eng %": round(sum(eng) / len(eng), 2) if eng else 0.0,
            "Best Video": best.get("Title"),
            "Best Video Views": best.get("Views"),
            "Best Video Link": best.get("Video Link"),
            "Channel Keywords": first.get("Channel Keywords"),
            "Channel Topics": first.get("Channel Topics"),
        })
    out.sort(key=lambda r: (_num(r.get("Sample Views")), _num(r.get("Subscribers"))), reverse=True)
    return out


def _share(rows: list[dict], key: str, value: str = "yes") -> str:
    if not rows:
        return "0%"
    hits = sum(1 for r in rows if r.get(key) == value)
    return f"{round(hits / len(rows) * 100)}%"


def build_summary(topic: str, args, rows: list[dict], quota_used: str,
                  now: dt.datetime | None = None) -> list[tuple[str, object]]:
    now = now or dt.datetime.now()
    views = [int(_num(r.get("Views"))) for r in rows if r.get("Views") is not None]
    eng = [_num(r.get("Engagement %")) for r in rows]
    durations = [_num(r.get("Duration s")) for r in rows if r.get("Duration s") is not None]
    dates = sorted(r.get("Published") for r in rows if r.get("Published"))
    tag_counter: Counter = Counter()
    for r in rows:
        for t in (r.get("Tags") or "").split(", "):
            if t:
                tag_counter[t.lower()] += 1
    channel_counter = Counter(r.get("Handle") or r.get("Creator") for r in rows)
    cat_counter = Counter(r.get("Category") for r in rows if r.get("Category"))
    lang_counter = Counter(r.get("Language") for r in rows if r.get("Language"))
    country_counter = Counter(r.get("Channel Country") for r in rows if r.get("Channel Country"))
    filters = f"max {args.max}, since {args.since}, length {args.length}, sort {args.sort}"
    if getattr(args, "comments", None):
        filters += f", comments {args.comments}"
    if getattr(args, "hooks", None):
        filters += f", hooks {args.hooks}s"
    if getattr(args, "transcribe", None):
        filters += f", transcribe {args.transcribe}"
    top = rows[0] if rows else {}
    return [
        ("Topic", topic),
        ("Run date", now.strftime("%Y-%m-%d %H:%M")),
        ("Filters", filters),
        ("Videos", len(rows)),
        ("Quota used", quota_used),
        ("Total views", sum(views)),
        ("Median views", int(statistics.median(views)) if views else 0),
        ("Mean views", int(statistics.mean(views)) if views else 0),
        ("Avg engagement %", round(sum(eng) / len(eng), 2) if eng else 0.0),
        ("Median duration s", int(statistics.median(durations)) if durations else 0),
        ("Shorts share", _share(rows, "Format", "Short")),
        ("Paid promotion share", _share(rows, "Paid Promotion")),
        ("Captions share", _share(rows, "Captions")),
        ("Published range", f"{dates[0]} to {dates[-1]}" if dates else ""),
        ("Top video", f"{top.get('Title', '')} ({int(_num(top.get('Views'))):,} views)" if top else ""),
        ("Top channels (videos in sample)",
         ", ".join(f"{k} ({v})" for k, v in channel_counter.most_common(10))),
        ("Top tags", ", ".join(f"{k} ({v})" for k, v in tag_counter.most_common(15))),
        ("Categories", ", ".join(f"{k} ({v})" for k, v in cat_counter.most_common(5))),
        ("Languages", ", ".join(f"{k} ({v})" for k, v in lang_counter.most_common(5))),
        ("Channel countries", ", ".join(f"{k} ({v})" for k, v in country_counter.most_common(5))),
    ]


# --------------------------------------------------------------------------- #
# Workbook I/O
# --------------------------------------------------------------------------- #

def _openpyxl():
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ScoutError(
            "openpyxl is not installed. Run: pip install openpyxl", EXIT_FILE
        ) from None
    return Workbook, load_workbook, Font, PatternFill, get_column_letter


def style_header(ws, columns: list[str], keep_widths: bool = False) -> None:
    _, _, Font, PatternFill, get_column_letter = _openpyxl()
    fill = PatternFill(fill_type="solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
    font = Font(name="Arial", bold=True, color="FFFFFFFF")
    for idx, name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=idx, value=name)
        cell.fill = fill
        cell.font = font
        letter = get_column_letter(idx)
        existing = ws.column_dimensions[letter].width if letter in ws.column_dimensions else None
        if keep_widths and existing:
            continue
        width = COLUMN_WIDTHS.get(name)
        if width:
            ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(ws.max_row, 2)}"


def write_rows(ws, columns: list[str], rows: list[dict], start_row: int) -> None:
    _, _, Font, _, _ = _openpyxl()
    link_font = Font(color=LINK_FONT_COLOR, underline="single")
    for r_off, row in enumerate(rows):
        r = start_row + r_off
        links = row.get(HYPERLINK_KEY) or {}
        fonts = row.get(FONT_KEY) or {}
        for c_idx, name in enumerate(columns, start=1):
            value = row.get(name)
            if isinstance(value, str) and len(value) > EXCEL_CELL_MAX:
                value = value[:EXCEL_CELL_MAX]
            cell = ws.cell(row=r, column=c_idx, value=value)
            fmt = NUMBER_FORMATS.get(name)
            if fmt:
                cell.number_format = fmt
            target = links.get(name)
            if (not target and not row.get(EXISTING_KEY) and name in LINK_COLUMNS
                    and str(value or "").startswith("http")):
                target = value
            if target:
                cell.hyperlink = target
                cell.font = fonts.get(name) or link_font


def _finish_sheet(ws, columns: list[str], row_count: int) -> None:
    _, _, _, _, get_column_letter = _openpyxl()
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(row_count + 1, 2)}"


def add_sheet(wb, name: str, columns: list[str], rows: list[dict]):
    ws = wb.create_sheet(name)
    style_header(ws, columns)
    write_rows(ws, columns, rows, start_row=2)
    _finish_sheet(ws, columns, len(rows))
    return ws


def add_summary_sheet(wb, pairs: list[tuple[str, object]]):
    _, _, Font, PatternFill, _ = _openpyxl()
    ws = wb.create_sheet(SUMMARY_SHEET)
    fill = PatternFill(fill_type="solid", start_color=HEADER_FILL, end_color=HEADER_FILL)
    for r, (label, value) in enumerate(pairs, start=1):
        a = ws.cell(row=r, column=1, value=label)
        a.fill = fill
        a.font = Font(name="Arial", bold=True, color="FFFFFFFF")
        b = ws.cell(row=r, column=2, value=value)
        if isinstance(value, int) and not isinstance(value, bool):
            b.number_format = "#,##0"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 100
    return ws


def new_workbook_columns(rows: list[dict]) -> list[str]:
    """ALL_COLUMNS minus optional columns that are blank in every row."""
    def blank(name: str) -> bool:
        return all(r.get(name) in (None, "") for r in rows)
    return [c for c in ALL_COLUMNS if c not in OPTIONAL_COLUMNS or not blank(c)]


def _save(wb, path: Path) -> None:
    try:
        wb.save(path)
    except PermissionError:
        raise ScoutError(
            f"Cannot write {path}: it is open in another program or read-only. "
            f"Close it and rerun.", EXIT_FILE) from None
    except OSError as exc:
        raise ScoutError(f"Cannot write {path}: {exc}", EXIT_FILE) from None


def write_workbook(rows: list[dict], path: Path, *, channel_rows: list[dict] | None = None,
                   comment_rows: list[dict] | None = None,
                   transcript_rows: list[dict] | None = None,
                   summary: list[tuple[str, object]] | None = None) -> Path:
    Workbook, _, _, _, _ = _openpyxl()
    columns = new_workbook_columns(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    style_header(ws, columns)
    write_rows(ws, columns, rows, start_row=2)
    _finish_sheet(ws, columns, len(rows))
    if channel_rows:
        add_sheet(wb, CHANNELS_SHEET, CHANNEL_COLUMNS, channel_rows)
    if comment_rows:
        add_sheet(wb, COMMENTS_SHEET, COMMENT_COLUMNS, comment_rows)
    if transcript_rows:
        add_sheet(wb, TRANSCRIPTS_SHEET, TRANSCRIPT_COLUMNS, transcript_rows)
    if summary:
        add_summary_sheet(wb, summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    _save(wb, path)
    return path


def backup_workbook(path: Path, now: dt.datetime | None = None) -> Path:
    """Copy the workbook next to itself before an --into rewrite."""
    import shutil
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def read_existing_rows(ws) -> tuple[list[str], list[dict]]:
    header = [c.value for c in ws[1]]
    columns = [str(h) for h in header if h is not None]
    rows: list[dict] = []
    for cells in ws.iter_rows(min_row=2):
        values = [c.value for c in cells]
        if all(v is None or v == "" for v in values[:len(columns)]):
            continue
        row = {name: values[i] if i < len(values) else None for i, name in enumerate(columns)}
        row[EXISTING_KEY] = True
        links = {
            columns[i]: c.hyperlink.target
            for i, c in enumerate(cells[:len(columns)])
            if c.hyperlink and c.hyperlink.target
        }
        if links:
            row[HYPERLINK_KEY] = links
            row[FONT_KEY] = {
                columns[i]: copy(c.font) for i, c in enumerate(cells[:len(columns)])
                if columns[i] in links
            }
        rows.append(row)
    return columns, rows


def strip_meta(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in META_KEYS}


def append_workbook(rows: list[dict], path: Path, sort: str, *,
                    comment_rows: list[dict] | None = None,
                    transcript_rows: list[dict] | None = None) -> tuple[Path, int, int]:
    """Append rows into an existing workbook's Videos sheet.

    Returns (path, added, skipped_duplicates). The whole data body is rewritten
    sorted by `sort`; existing manual columns, hyperlinks, and widths are preserved.
    Comment and transcript rows go into their own sheets, created on demand and
    deduplicated by Video ID.
    """
    _, load_workbook, _, _, _ = _openpyxl()
    if not path.exists():
        raise ScoutError(f"--into file does not exist: {path}", EXIT_FILE)
    backup_workbook(path)
    wb = load_workbook(path)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
    columns, existing = read_existing_rows(ws)
    if not columns:
        columns = list(ALL_COLUMNS)
    for name in ALL_COLUMNS:
        if name not in columns:
            columns.append(name)
    existing_ids = {str(r.get("Video ID")) for r in existing if r.get("Video ID")}
    new_rows = [r for r in rows if r["Video ID"] not in existing_ids]
    skipped = len(rows) - len(new_rows)
    merged = sorted(existing + new_rows, key=sort_key(sort), reverse=True)

    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)
    style_header(ws, columns, keep_widths=True)
    write_rows(ws, columns, merged, start_row=2)
    _finish_sheet(ws, columns, len(merged))

    for sheet_name, sheet_columns, extra in (
        (COMMENTS_SHEET, COMMENT_COLUMNS, comment_rows),
        (TRANSCRIPTS_SHEET, TRANSCRIPT_COLUMNS, transcript_rows),
    ):
        if not extra:
            continue
        if sheet_name in wb.sheetnames:
            sub = wb[sheet_name]
            sub_columns, sub_existing = read_existing_rows(sub)
            have = {str(r.get("Video ID")) for r in sub_existing}
            fresh = [r for r in extra if r["Video ID"] not in have]
            write_rows(sub, sub_columns or sheet_columns, fresh, start_row=sub.max_row + 1)
            _finish_sheet(sub, sub_columns or sheet_columns, sub.max_row - 1)
        else:
            add_sheet(wb, sheet_name, sheet_columns, extra)
    _save(wb, path)
    return path, len(new_rows), skipped


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def fmt_int(value) -> str:
    return f"{int(value):,}" if isinstance(value, (int, float)) else "-"


def fmt_duration(seconds) -> str:
    if seconds is None:
        return "-"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def print_summary(rows: list[dict], limit: int = 10) -> str:
    lines = [f"{'#':>2}  {'Views':>11}  {'Eng %':>6}  {'V/day':>8}  {'V/Sub':>6}  {'Len':>7}  "
             f"{'Fmt':<5} {'Handle':<20} Title"]
    for i, r in enumerate(rows[:limit], start=1):
        title = (r.get("Title") or "")[:50]
        vsub = r.get("Views/Sub")
        lines.append(
            f"{i:>2}  {fmt_int(r.get('Views')):>11}  {_num(r.get('Engagement %')):>6.2f}  "
            f"{fmt_int(r.get('Views/day')):>8}  {(f'{vsub:.1f}' if vsub is not None else '-'):>6}  "
            f"{fmt_duration(r.get('Duration s')):>7}  {(r.get('Format') or '')[:5]:<5} "
            f"{(r.get('Handle') or '-')[:20]:<20} {title}"
        )
    return "\n".join(lines)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "topic"


def default_out_path(topic: str, today: dt.date | None = None) -> Path:
    today = today or dt.date.today()
    return Path.cwd() / f"scout-{slugify(topic)}-{today.isoformat()}.xlsx"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scout",
        description="Search YouTube for a topic and write a ranked research workbook.",
    )
    p.add_argument("topic", nargs="+", help="Search topic (quote it or pass words)")
    p.add_argument("--max", type=int, default=50, help="Videos to collect, 1 to 200 (default 50)")
    p.add_argument("--since", choices=SINCE_CHOICES, default="any")
    p.add_argument("--length", choices=LENGTH_CHOICES, default="any")
    p.add_argument("--sort", choices=SORT_CHOICES, default="views")
    p.add_argument("--out", type=Path, help="New workbook path (default scout-<topic>-<date>.xlsx)")
    p.add_argument("--into", type=Path, help="Append into an existing workbook's Videos sheet")
    p.add_argument("--comments", type=int, nargs="?", const=20, default=0, metavar="N",
                   help="Fetch top N comments per video (default 20), 1 quota unit per video")
    p.add_argument("--hooks", type=float, nargs="?", const=15.0, default=0.0, metavar="SECONDS",
                   help="Use yt-dlp for hook transcript (first SECONDS, default 15), vertical, "
                        "replay heatmap, full transcript. No quota, slower.")
    p.add_argument("--download", type=int, nargs="?", const=0, default=None, metavar="N",
                   help="Save thumbnails for every video and mp4s for the top N into ./downloads "
                        "(all videos when N is omitted)")
    p.add_argument("--transcribe", nargs="?", const="turbo", default=None, metavar="MODEL",
                   help="Transcribe audio locally with Whisper for videos without caption "
                        "transcripts (default model turbo, GPU recommended). Fills Hook, "
                        "Transcript Words, and the Transcripts sheet. No quota, no caption requests.")
    p.add_argument("--dry-run", action="store_true", help="Fetch and print, write nothing")
    p.add_argument("--json", action="store_true", help="Also print rows as JSON")
    return p


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    topic = " ".join(args.topic).strip()
    if not topic or len(topic) > 200:
        print("scout: topic must be 1 to 200 characters", file=sys.stderr)
        return EXIT_USAGE
    if not 1 <= args.max <= 200:
        print("scout: --max must be between 1 and 200", file=sys.stderr)
        return EXIT_USAGE
    if args.out and args.into:
        print("scout: use either --out or --into, not both", file=sys.stderr)
        return EXIT_USAGE
    if args.comments < 0 or args.comments > 100:
        print("scout: --comments must be between 1 and 100", file=sys.stderr)
        return EXIT_USAGE

    def progress(msg: str) -> None:
        print(f"scout: {msg}", file=sys.stderr, flush=True)

    try:
        api_key = load_api_key()
        quota = Quota()
        progress(f"searching YouTube for \"{topic}\" (max {args.max}, since {args.since}, "
                 f"length {args.length})")
        ids = search_ids(topic, args.max, args.since, args.length, api_key, quota)
        if not ids:
            progress("no videos found for that topic and filters.")
            return EXIT_OK
        relevance = {vid: i for i, vid in enumerate(ids, start=1)}
        videos = fetch_videos(ids, api_key, quota)
        channel_ids = sorted({(v.get("snippet") or {}).get("channelId", "") for v in videos} - {""})
        warnings: list[str] = []
        try:
            channels = fetch_channels(channel_ids, api_key, quota)
        except ScoutError as exc:
            if exc.code in (EXIT_QUOTA, EXIT_BAD_KEY):
                raise
            channels = {}
            warnings.append(f"channel lookup failed, handles blank: {exc}")
        try:
            categories = fetch_categories(api_key, quota)
        except ScoutError as exc:
            if exc.code in (EXIT_QUOTA, EXIT_BAD_KEY):
                raise
            categories = {}
            warnings.append(f"category lookup failed: {exc}")
        rows = sort_rows(build_rows(videos, channels, categories, relevance), args.sort)

        comment_rows: list[dict] = []
        transcript_rows: list[dict] = []
        if args.comments:
            progress(f"fetching top {args.comments} comments for {len(rows)} videos")
            comment_rows, w = enrich_comments(rows, args.comments, api_key, quota, progress)
            warnings.extend(w)
        if args.hooks:
            progress(f"probing {len(rows)} videos with yt-dlp for hooks and replay data")
            transcript_rows, w = enrich_hooks(rows, args.hooks, progress, cache_dir=CACHE_DIR,
                                              transcribe_after=bool(args.transcribe))
            warnings.extend(w)
            rows = sort_rows(rows, args.sort)
        if args.download is not None and not args.dry_run:
            n_videos = args.download if args.download > 0 else len(rows)
            progress(f"downloading {len(rows)} thumbnails and {min(n_videos, len(rows))} videos")
            warnings.extend(download_videos(rows, Path.cwd() / "downloads", n_videos))
        if args.transcribe:
            pending = sum(1 for r in rows if not r.get("Transcript Words"))
            progress(f"transcribing {pending} videos locally with Whisper ({args.transcribe})")
            try:
                more, w = enrich_transcribe(
                    rows, args.hooks or 15.0, Transcriber(args.transcribe),
                    media_dir=Path.cwd() / "downloads", cache_dir=CACHE_DIR, progress=progress)
                transcript_rows.extend(more)
                warnings.extend(w)
            except ScoutError as exc:
                warnings.append(str(exc))

        print(print_summary(rows))
        print()
        if args.json:
            print(json.dumps([strip_meta(r) for r in rows], ensure_ascii=False, indent=2))
        sys.stdout.flush()

        if args.dry_run:
            progress(f"dry run, {len(rows)} rows fetched, nothing written. "
                     f"Quota used: {quota.summary()}.")
        elif args.into:
            path, added, skipped = append_workbook(
                rows, args.into, args.sort,
                comment_rows=comment_rows, transcript_rows=transcript_rows)
            progress(f"appended {added} rows to {path} ({skipped} already present). "
                     f"Quota used: {quota.summary()}.")
        else:
            path = write_workbook(
                rows, args.out or default_out_path(topic),
                channel_rows=build_channel_rows(rows),
                comment_rows=comment_rows,
                transcript_rows=transcript_rows,
                summary=build_summary(topic, args, rows, quota.summary()),
            )
            sheets = [SHEET_NAME, CHANNELS_SHEET] + ([COMMENTS_SHEET] if comment_rows else []) \
                + ([TRANSCRIPTS_SHEET] if transcript_rows else []) + [SUMMARY_SHEET]
            progress(f"wrote {len(rows)} rows to {path} (sheets: {', '.join(sheets)}). "
                     f"Quota used: {quota.summary()}.")
        for w in warnings:
            print(f"scout: warning: {w}", file=sys.stderr)
        return EXIT_OK
    except ScoutError as exc:
        print(f"scout: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(run())
