# Security

## Reporting a vulnerability

Report security issues privately through GitHub's "Report a vulnerability" form on this
repository, or by contacting the maintainer through the channels in `SUPPORT.md`. Please do not
open a public issue for a vulnerability. You will get an acknowledgement within a few days.

## Scope

youtube-scout is a local command-line skill. It makes outbound HTTPS requests to
`www.googleapis.com` (YouTube Data API v3) and, with `--hooks` or `--download`, runs `yt-dlp`
against `youtube.com`. It writes workbooks into the current directory and a probe cache under
`~/.cache/scout/`. It never uploads anything.

## Credentials

- The YouTube API key is read from the `YOUTUBE_API_KEY` environment variable, the file named
  by `SCOUT_ENV_FILE`, `~/.config/scout/.env`, or `./.env`. It is never written to disk,
  logged, or included in error messages.
- Keep the key file readable only by you (`chmod 600`). Restrict the key in Google Cloud to the
  YouTube Data API v3.
- If a key is ever exposed, rotate it in Google Cloud Console first, then remove the exposure.

## Data handling

Generated workbooks contain public data about third-party creators (names, handles, comments,
transcripts). Treat them as research material: do not commit them (the `.gitignore` blocks
`*.xlsx`) and do not redistribute them.

## Automated checks

CI runs `detect-secrets`, a regex gate for known credential shapes, and a hygiene test that
rejects local absolute paths, key file references, and tracked workbooks.
