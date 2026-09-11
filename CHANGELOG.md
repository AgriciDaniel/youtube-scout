# Changelog

All notable changes to youtube-scout are recorded here. The format follows Keep a Changelog
and the project uses semantic versioning.

## 0.2.0 - 2026-09-11

### Added

- `--transcribe [MODEL]`: local Whisper transcription (OpenAI whisper on GPU, faster-whisper on
  CPU) for every video without a caption transcript. Fills Hook, Transcript Words, and the
  Transcripts sheet without touching YouTube's caption endpoint, cached per video.
- Transcript Source column (Videos) and Source column (Transcripts): `captions` or `whisper`.
- `--download [N]`: thumbnails for every video, mp4s for the top N only.

### Changed

- Caption rate-limit guidance: the block is per IP and can last hours, not one hour.

## 0.1.1 - 2026-09-11

### Fixed

- Quota accounting now follows the YouTube Data API granular quota system introduced on
  2026-06-01: `search.list` draws from its own bucket of 100 calls a day, other reads cost
  1 unit each from 10,000 a day. Runs report "1 search call of 100 a day, 3 units of 10,000"
  instead of the old "103 units", and the Summary sheet row is renamed "Quota used".

## 0.1.0 - 2026-09-11

First private release.

### Added

- `/scout <topic>`: YouTube Data API v3 search, statistics, channel, and category lookups,
  ranked by views, engagement, likes, recency, momentum, or breakout.
- Videos sheet in the OWT-Social-Ads layout with 48 columns (64 in append mode), Channels sheet
  for creator outreach, Summary sheet with sample aggregates.
- `--comments [N]`: top comments per video into a Comments sheet plus Top Comment on each row.
- `--hooks [SECONDS]`: yt-dlp probe for hook text, vertical detection, FPS, replay hotspots from
  the "most replayed" curve, chapters, and full transcripts in a Transcripts sheet, with an
  on-disk cache, request pacing, backoff, and a circuit breaker for caption rate limits.
- `--into file.xlsx`: append into an existing workbook with Video ID dedup, re-sort, preserved
  hyperlinks, fonts, and widths, and a timestamped backup written first.
- `--download`: mp4 and thumbnail download with yt-dlp.
- Key lookup from `YOUTUBE_API_KEY`, `SCOUT_ENV_FILE`, `~/.config/scout/.env`, or `./.env`.
- Offline test suite with API-shaped fixtures and a repository hygiene test.
