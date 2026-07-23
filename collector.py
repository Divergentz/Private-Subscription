#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import json
import os
import re
import socket
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, parse_qs, unquote

import requests

OUTPUT_MAIN = os.getenv("OUTPUT_MAIN", "divergentz.txt")
OUTPUT_ALL = os.getenv("OUTPUT_ALL", "all-configs.txt")
OUTPUT_REPORT = os.getenv("OUTPUT_REPORT", "health-report.json")

MAX_COLLECTED = int(os.getenv("MAX_COLLECTED", "1000"))
MAX_TESTED = int(os.getenv("MAX_TESTED", "300"))
MAX_WORKING = int(os.getenv("MAX_WORKING", "100"))
TEST_CONCURRENCY = int(os.getenv("TEST_CONCURRENCY", "50"))
CONNECT_TIMEOUT = float(os.getenv("CONNECT_TIMEOUT", "3"))

SUPPORTED_SCHEMES = (
    "vless", "vmess", "trojan", "ss", "ssr",
    "hysteria2", "hy2", "tuic"
)
URI_PATTERN = re.compile(
    rf"(?:(?:{'|'.join(SUPPORTED_SCHEMES)})://)[^\s<>'\"`]+",
    re.IGNORECASE,
)
USER_AGENT = "Mozilla/5.0 (compatible; DivergentzSubscription/2.0)"


@dataclass
class ParsedConfig:
    uri: str
    protocol: str
    host: str | None
    port: int | None
    source: str
    parse_status: str
    latency_ms: float | None = None
    test_status: str | None = None
    error: str | None = None


def load_sources() -> list[str]:
    raw = os.getenv("SOURCE_URLS", "").strip()
    if not raw:
        raise RuntimeError("SOURCE_URLS repository secret is empty.")
    sources = []
    for line in raw.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            if not value.startswith(("https://", "http://")):
                raise RuntimeError(f"Invalid source URL: {value}")
            sources.append(value)
    if not sources:
        raise RuntimeError("No usable source URLs were provided.")
    return sources


def fetch(url: str) -> str:
    response = requests.get(
        url,
        timeout=25,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def clean_uri(value: str) -> str:
    return html.unescape(value).strip().rstrip(".,;")


def extract_uris(text: str) -> list[str]:
    return [clean_uri(m.group(0)) for m in URI_PATTERN.finditer(html.unescape(text))]


def canonical_key(uri: str) -> str:
    try:
        parts = urlsplit(uri)
        normalized = f"{parts.scheme.lower()}://{parts.netloc}{parts.path}"
        if parts.query:
            normalized += f"?{parts.query}"
    except Exception:
        normalized = uri.split("#", 1)[0]
    return hashlib.sha256(normalized.encode("utf-8", "ignore")).hexdigest()


def deduplicate(items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    output = []
    seen = set()
    for uri, source in items:
        key = canonical_key(uri)
        if key not in seen:
            seen.add(key)
            output.append((uri, source))
    return output


def b64decode_loose(value: str) -> bytes:
    value = value.strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def parse_host_port(uri: str, source: str) -> ParsedConfig:
    protocol = uri.split("://", 1)[0].lower()
    try:
        if protocol == "vmess":
            payload = uri.split("://", 1)[1].split("#", 1)[0]
            data = json.loads(b64decode_loose(payload).decode("utf-8"))
            host = str(data.get("add") or "").strip()
            port = int(data.get("port"))
        elif protocol == "ss":
            body = uri.split("://", 1)[1].split("#", 1)[0]
            # SIP002 can be userinfo@host:port or a fully base64-encoded body.
            decoded = body
            if "@" not in decoded:
                decoded = b64decode_loose(decoded).decode("utf-8")
            target = decoded.rsplit("@", 1)[-1]
            if target.startswith("["):
                host, remainder = target[1:].split("]", 1)
                port = int(remainder.lstrip(":").split("?", 1)[0])
            else:
                host, port_text = target.rsplit(":", 1)
                port = int(port_text.split("?", 1)[0])
        elif protocol == "ssr":
            decoded = b64decode_loose(uri.split("://", 1)[1]).decode("utf-8")
            core = decoded.split("/?", 1)[0]
            host, port_text, *_ = core.split(":")
            port = int(port_text)
        else:
            parsed = urlsplit(uri)
            host = parsed.hostname
            port = parsed.port

        if not host or not port or not (1 <= port <= 65535):
            raise ValueError("missing or invalid host/port")

        return ParsedConfig(uri, protocol, host, port, source, "parsed")
    except Exception as exc:
        return ParsedConfig(
            uri, protocol, None, None, source, "parse_failed",
            test_status="parse_failed", error=str(exc)[:300]
        )


async def tcp_test(item: ParsedConfig, semaphore: asyncio.Semaphore) -> ParsedConfig:
    if item.parse_status != "parsed" or not item.host or not item.port:
        return item

    async with semaphore:
        started = time.perf_counter()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(item.host, item.port),
                timeout=CONNECT_TIMEOUT,
            )
            item.latency_ms = round((time.perf_counter() - started) * 1000, 1)
            item.test_status = "passed_tcp"
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except asyncio.TimeoutError:
            item.test_status = "timeout"
        except socket.gaierror as exc:
            item.test_status = "dns_failed"
            item.error = str(exc)[:300]
        except ConnectionRefusedError as exc:
            item.test_status = "connection_refused"
            item.error = str(exc)[:300]
        except OSError as exc:
            item.test_status = "network_error"
            item.error = str(exc)[:300]
        except Exception as exc:
            item.test_status = "test_failed"
            item.error = str(exc)[:300]
        return item


async def run_tests(items: list[ParsedConfig]) -> list[ParsedConfig]:
    semaphore = asyncio.Semaphore(TEST_CONCURRENCY)
    return await asyncio.gather(*(tcp_test(i, semaphore) for i in items))


def write_lines(path: str, lines: list[str]) -> None:
    Path(path).write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )


def main() -> int:
    sources = load_sources()
    collected: list[tuple[str, str]] = []
    source_results = []

    for url in sources:
        try:
            text = fetch(url)
            found = extract_uris(text)
            collected.extend((uri, url) for uri in found)
            source_results.append({"url": url, "status": "ok", "extracted": len(found)})
            print(f"[OK] {url}: {len(found)}")
        except Exception as exc:
            source_results.append({"url": url, "status": "error", "error": str(exc)[:500]})
            print(f"[ERROR] {url}: {exc}")

    unique = deduplicate(collected)[:MAX_COLLECTED]
    parsed = [parse_host_port(uri, source) for uri, source in unique]

    # Test only the first MAX_TESTED parseable configs to bound runtime.
    testable = [item for item in parsed if item.parse_status == "parsed"][:MAX_TESTED]
    tested_by_uri = {item.uri: item for item in asyncio.run(run_tests(testable))}

    final_items = []
    for item in parsed:
        final_items.append(tested_by_uri.get(item.uri, item))

    working = sorted(
        [i for i in final_items if i.test_status == "passed_tcp"],
        key=lambda x: (x.latency_ms is None, x.latency_ms or 10**9),
    )[:MAX_WORKING]

    all_uris = [i.uri for i in final_items]
    working_uris = [i.uri for i in working]

    write_lines(OUTPUT_ALL, all_uris)
    write_lines(OUTPUT_MAIN, working_uris)
    # Backward-compatible alias.
    write_lines("sub.txt", working_uris)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": (
            "passed_tcp means only that the server host and port accepted a TCP "
            "connection from GitHub Actions. It does not prove that the full proxy "
            "protocol, authentication, TLS/Reality, or access from Iran works."
        ),
        "settings": {
            "max_collected": MAX_COLLECTED,
            "max_tested": MAX_TESTED,
            "max_working": MAX_WORKING,
            "test_concurrency": TEST_CONCURRENCY,
            "connect_timeout_seconds": CONNECT_TIMEOUT,
        },
        "counts": {
            "sources": len(sources),
            "collected": len(collected),
            "unique": len(unique),
            "parsed": sum(i.parse_status == "parsed" for i in final_items),
            "tested": len(tested_by_uri),
            "passed_tcp": len(working),
        },
        "sources": source_results,
        "configs": [asdict(i) for i in final_items],
    }
    Path(OUTPUT_REPORT).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
