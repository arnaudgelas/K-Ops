from __future__ import annotations

import argparse
import json
import mimetypes
import hashlib
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests import RequestException

from utils import CONFIG, ROOT, ensure_dir, load_json, now_stamp, save_json, short_hash, slugify

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir

ARXIV_ARTICLE_RE = re.compile(r"^/(?:abs|html|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)")


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def read_input_list(path: Path) -> list[str]:
    items: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages).strip()


def extract_html_text(raw_html: str, url: str) -> str:
    extracted = trafilatura.extract(raw_html, url=url, include_comments=False, include_tables=True)
    if extracted:
        return extracted.strip()
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text("\n", strip=True)


def fetch_url(url: str) -> tuple[bytes, str | None, str, str]:
    response = requests.get(url, timeout=30, headers={"User-Agent": "living-kb-cli/0.1"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    filename = Path(urlparse(url).path).name or "downloaded"
    return response.content, response.text if "text" in content_type or "html" in content_type else None, content_type, filename


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_arxiv_url(url: str) -> bool:
    return urlparse(url).netloc.endswith("arxiv.org")


def arxiv_candidate_urls(url: str) -> list[str]:
    parsed = urlparse(url)
    match = ARXIV_ARTICLE_RE.match(parsed.path)
    if not match:
        return [url]

    article_id = match.group("id")
    base_id = article_id.split("v", 1)[0]
    candidates: list[str] = []
    if parsed.path.startswith("/html/") or parsed.path.startswith("/pdf/"):
        candidates.append(url)
    else:
        candidates.extend(
            [
                f"https://arxiv.org/html/{article_id}",
                f"https://arxiv.org/html/{base_id}v1",
                f"https://arxiv.org/pdf/{article_id}.pdf",
                f"https://arxiv.org/pdf/{base_id}v1.pdf",
            ]
        )

    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def fetch_arxiv_article(url: str) -> tuple[bytes, str | None, str, str, str]:
    last_error: Exception | None = None
    for candidate in arxiv_candidate_urls(url):
        try:
            raw_bytes, maybe_text, content_type, filename = fetch_url(candidate)
            return raw_bytes, maybe_text, content_type, filename, candidate
        except RequestException as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise RequestException(f"Unable to fetch arXiv article: {url}")


def ingest_one(item: str) -> dict:
    source_id = f"src-{short_hash(item)}"
    source_dir = RAW_DIR / source_id
    ensure_dir(source_dir)
    metadata: dict = {
        "id": source_id,
        "source": item,
        "ingested_at": now_stamp(),
    }
    original_bytes: bytes

    if is_url(item):
        if is_arxiv_url(item):
            raw_bytes, maybe_text, content_type, filename, resolved_url = fetch_arxiv_article(item)
        else:
            raw_bytes, maybe_text, content_type, filename = fetch_url(item)
            resolved_url = item
        original_bytes = raw_bytes
        suffix = Path(filename).suffix or mimetypes.guess_extension(content_type.split(";")[0]) or ".bin"
        original_path = source_dir / f"original{suffix}"
        original_path.write_bytes(raw_bytes)
        metadata.update({
            "kind": "url",
            "content_type": content_type,
            "original_path": str(original_path.relative_to(ROOT)),
            "resolved_url": resolved_url,
        })

        normalized = ""
        if "pdf" in content_type or suffix.lower() == ".pdf":
            normalized = extract_pdf_text(original_path)
        elif maybe_text is not None:
            normalized = extract_html_text(maybe_text, item)
        else:
            normalized = ""
    else:
        path = Path(item)
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Missing local source: {item}")
        suffix = path.suffix.lower()
        copied_path = source_dir / f"original{suffix or '.txt'}"
        shutil.copy2(path, copied_path)
        original_bytes = copied_path.read_bytes()
        metadata.update({
            "kind": "file",
            "content_type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
            "original_path": str(copied_path.relative_to(ROOT)),
        })
        if suffix == ".pdf":
            normalized = extract_pdf_text(copied_path)
        else:
            normalized = path.read_text(encoding="utf-8", errors="ignore")

    normalized_path = source_dir / "normalized.md"
    normalized_path.write_text(normalized.strip() + "\n", encoding="utf-8")
    metadata["normalized_path"] = str(normalized_path.relative_to(ROOT))
    metadata["title_guess"] = slugify(item).replace("_", " ").title()
    metadata["content_hash"] = content_hash(original_bytes)
    metadata["last_checked_at"] = now_stamp()
    (source_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def upsert_registry_entry(entry: dict) -> None:
    registry = load_json(REGISTRY_PATH, default=[])
    existing = {item["id"]: index for index, item in enumerate(registry)}
    index = existing.get(entry["id"])
    if index is None:
        registry.append(entry)
    else:
        registry[index] = entry
    save_json(REGISTRY_PATH, registry)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to a newline-delimited list of URLs or local paths")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first ingestion error instead of continuing with the remaining sources.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch and overwrite existing sources instead of skipping items already present in the registry.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (ROOT / input_path).resolve()

    items = read_input_list(input_path)
    registry = load_json(REGISTRY_PATH, default=[])
    existing_sources = {entry["source"] for entry in registry}

    new_entries = []
    failures: list[tuple[str, str]] = []
    for item in items:
        if item in existing_sources and not args.refresh:
            print(f"Skipping already ingested source: {item}")
            continue
        try:
            entry = ingest_one(item)
        except (FileNotFoundError, RequestException, OSError, ValueError) as exc:
            message = str(exc).strip() or exc.__class__.__name__
            failures.append((item, message))
            print(f"Failed to ingest {item}: {message}")
            if args.fail_fast:
                break
            continue

        new_entries.append(entry)
        print(f"Ingested {item} -> {entry['id']}")

    if new_entries:
        if args.refresh:
            for entry in new_entries:
                existing = {item["id"]: index for index, item in enumerate(registry)}
                index = existing.get(entry["id"])
                if index is None:
                    registry.append(entry)
                else:
                    registry[index] = entry
        else:
            registry.extend(new_entries)
        save_json(REGISTRY_PATH, registry)
        action = "Refreshed" if args.refresh else "Updated"
        print(f"{action} registry with {len(new_entries)} source(s)")
    else:
        print("No new sources ingested" if not args.refresh else "No sources refreshed")

    if failures:
        print("")
        print(f"Ingestion completed with {len(failures)} failure(s):")
        for item, message in failures:
            print(f"- {item}: {message}")


if __name__ == "__main__":
    main()
