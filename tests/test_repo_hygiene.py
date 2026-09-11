"""Repository hygiene: no em dashes, no local paths, no key file references, no workbooks.

Runs against `git ls-files` when inside a git checkout, otherwise walks the tree.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

# Built from fragments so this file does not trip its own checks.
EM_DASH = "\u2014"
LOCAL_PATHS = ["/var" + "/home/", "/home/", "/Users/", "Desktop" + "/Keys", "agricidaniel@"]
CREDENTIAL = re.compile(
    r"AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|gh[ous]_[A-Za-z0-9]{36}"
    r"|AKIA[0-9A-Z]{16}|GOCSPX-[A-Za-z0-9_-]{20,}|sk-(proj-)?[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}"
)
TEXT_SUFFIXES = {".py", ".md", ".sh", ".yml", ".yaml", ".json", ".toml", ".txt", ".json3", ".cff", ""}


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                             capture_output=True).stdout
        files = [ROOT / p for p in out.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [p for p in files if p.exists()]


def text_files() -> list[Path]:
    return [p for p in tracked_files() if p.suffix in TEXT_SUFFIXES and p != SELF]


def test_no_em_dashes():
    offenders = [str(p.relative_to(ROOT)) for p in text_files()
                 if EM_DASH in p.read_text(encoding="utf-8", errors="replace")]
    assert offenders == [], f"em dash found in: {offenders}"


@pytest.mark.parametrize("needle", LOCAL_PATHS)
def test_no_local_paths_or_key_locations(needle):
    offenders = [str(p.relative_to(ROOT)) for p in text_files()
                 if needle in p.read_text(encoding="utf-8", errors="replace")]
    assert offenders == [], f"'{needle}' found in: {offenders}"


def test_no_credential_shapes():
    offenders = []
    for p in text_files():
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if CREDENTIAL.search(line) and not re.search(r"DUMMY|EXAMPLE|YOUR_|REDACTED|placeholder", line):
                offenders.append(f"{p.relative_to(ROOT)}:{i}")
    assert offenders == [], f"credential-shaped strings in: {offenders}"


def test_no_workbooks_or_media_tracked():
    bad = [str(p.relative_to(ROOT)) for p in tracked_files()
           if p.suffix.lower() in {".xlsx", ".xls", ".mp4", ".webm", ".jpg", ".png", ".env"}]
    assert bad == [], f"data or media files tracked: {bad}"


def test_versions_agree():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## (\S+) - \d{4}-\d{2}-\d{2}", changelog, re.M).group(1)
    assert plugin["version"] == version
    assert market["metadata"]["version"] == version
    assert market["plugins"][0]["version"] == version
    assert top == version


def test_plugin_manifest_shape():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "youtube-scout" and plugin["license"] == "MIT"
    assert plugin["skills"] == ["./"]
    assert (ROOT / "SKILL.md").exists() and (ROOT / "LICENSE").exists()
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: scout\n")
