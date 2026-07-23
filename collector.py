#!/usr/bin/env python3
"""
Collect proxy subscription URIs from user-authorized public text/web sources.

Supported schemes:
  vless://, vmess://, trojan://, ss://, ssr://,
  hysteria2://, hy2://, tuic://

Sources are read from:
  1) SOURCE_URLS environment variable (newline-separated), or
  2) sources.txt

The script writes:
  - sub.txt
  - metadata.json
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

import requests

SUPPORTED_SCHEMES = (
    "vless",
    "vmess",
    "trojan",
    "ss",
    "ssr",
    "hysteria2",
    "hy2",
    "tuic",
)

URI_PATTERN = re.compile(
    rf"(?:(?:{'|'.join(SUPPORTED_SCHEMES)})://)[^\s<>'\"`]+",
    re.IGNORECASE,
)

REQUEST_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (compatible; PrivateSubscriptionCollector/1.0; "
    "+https://github.com/)"
)


@dataclass
class SourceResult:
    url: str
    status: str
    extracted: int = 0
    error: str | None = None


def load_sources() -> list[str]:
    raw = os.getenv("SOURCE_URLS", "").strip()
    if raw:
        lines = raw.splitlines()
    else:
        path = Path("sources.txt")
        if not path.exists():
            raise FileNotFoundError(
                "No sources provided. Set SOURCE_URLS or create sources.txt."
            )
        lines = path.read_text(encoding="utf-8").splitlines()

    sources: list[str] = []
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if not value.startswith(("https://", "http://")):
            raise ValueError(f"Invalid source URL: {value}")
        sources.append(value)

    if not sources:
        raise ValueError("The source list is empty.")
    return sources


def fetch_text(url: str) -> str:
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"},
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def clean_uri(value: str) -> str:
    value = html.unescape(value).strip()
    # Remove common punctuation accidentally captured from prose/HTML.
    value = value.rstrip(".,;")
    return value


def canonical_key(uri: str) -> str:
    """
    Deduplicate links while ignoring display-name fragments (#Name).
    Keep query parameters because they may affect connectivity.
    """
    try:
        parts = urlsplit(uri)
        normalized = urlunsplit(
            (parts.scheme.lower(), parts.netloc, parts.path, parts.query, "")
        )
    except ValueError:
        normalized = uri.split("#", 1)[0]

    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


def is_plausible(uri: str) -> bool:
    lower = uri.lower()
    if not any(lower.startswith(f"{scheme}://") for scheme in SUPPORTED_SCHEMES):
        return False
    if len(uri) < 12 or len(uri) > 8192:
        return False
    if any(ch in uri for ch in ("\x00", "\r", "\n")):
        return False
    return True


def extract_uris(text: str) -> list[str]:
    decoded = html.unescape(text)
    found: list[str] = []
    for match in URI_PATTERN.finditer(decoded):
        uri = clean_uri(match.group(0))
        if is_plausible(uri):
            found.append(uri)
    return found


def deduplicate(items: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = canonical_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def main() -> int:
    try:
        sources = load_sources()
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    collected: list[str] = []
    results: list[SourceResult] = []

    for url in sources:
        try:
            text = fetch_text(url)
            uris = extract_uris(text)
            collected.extend(uris)
            results.append(SourceResult(url=url, status="ok", extracted=len(uris)))
            print(f"[OK] {url}: {len(uris)} URI(s)")
        except requests.RequestException as exc:
            results.append(
                SourceResult(url=url, status="error", error=str(exc)[:500])
            )
            print(f"[ERROR] {url}: {exc}", file=sys.stderr)

    unique = deduplicate(collected)
    Path("sub.txt").write_text(
        "\n".join(unique) + ("\n" if unique else ""),
        encoding="utf-8",
    )

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "collected_count": len(collected),
        "unique_count": len(unique),
        "sources": [asdict(item) for item in results],
    }
    Path("metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Done: {len(collected)} collected, "
        f"{len(unique)} unique, {len(sources)} source(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
