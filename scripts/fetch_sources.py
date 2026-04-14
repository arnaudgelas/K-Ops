from __future__ import annotations

import argparse
import json
import mimetypes
import hashlib
import os
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import requests
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader
from requests import RequestException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils import CONFIG, ROOT, ensure_dir, load_json, now_stamp, save_json, short_hash, slugify

REGISTRY_PATH = CONFIG.registry_path
RAW_DIR = CONFIG.raw_dir

ARXIV_ARTICLE_RE = re.compile(r"^/(?:abs|html|pdf)/(?P<id>\d{4}\.\d{4,5}(?:v\d+)?)")
ARTICLE_HOST_HINTS = ("medium.com", "substack.com")
ARTICLE_BODY_SELECTORS = (
    "article",
    "main article",
    '[data-testid="post-content"]',
    '[data-testid="article-body"]',
    "div.post-content",
    "div.available-content",
    "div.body",
    "div.markup",
    "div.body.markup",
    "main",
)
BOILERPLATE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "iframe",
    "form",
    "button",
    "header",
    "footer",
    "nav",
    "aside",
)
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
BOILERPLATE_LINE_PATTERNS = (
    re.compile(r"^subscribe$", re.IGNORECASE),
    re.compile(r"^sign in$", re.IGNORECASE),
    re.compile(r"^get the app$", re.IGNORECASE),
    re.compile(r"^share$", re.IGNORECASE),
    re.compile(r"^read more.*", re.IGNORECASE),
)


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


def strip_tracking_parameters(url: str) -> str:
    parsed = urlsplit(url)
    filtered_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in TRACKING_QUERY_PARAMS:
            continue
        if key.startswith(TRACKING_QUERY_PREFIXES):
            continue
        filtered_query.append((key, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered_query), parsed.fragment))


def is_article_host(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(netloc == host or netloc.endswith(f".{host}") for host in ARTICLE_HOST_HINTS)


def flatten_jsonld(value: object) -> list[dict]:
    items: list[dict] = []
    if isinstance(value, dict):
        items.append(value)
        for nested in value.values():
            items.extend(flatten_jsonld(nested))
    elif isinstance(value, list):
        for nested in value:
            items.extend(flatten_jsonld(nested))
    return items


def extract_jsonld_article_body(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    bodies: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload = script.string or script.get_text(strip=True)
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for item in flatten_jsonld(parsed):
            article_body = item.get("articleBody")
            if isinstance(article_body, str):
                text = article_body.strip()
                if text:
                    bodies.append(text)
    if not bodies:
        return ""
    return max(bodies, key=len)


def clean_article_text(text: str) -> str:
    lines: list[str] = []
    previous_blank = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if not previous_blank and lines:
                lines.append("")
            previous_blank = True
            continue
        if any(pattern.match(line) for pattern in BOILERPLATE_LINE_PATTERNS):
            continue
        lines.append(line)
        previous_blank = False
    return "\n".join(lines).strip()


def extract_selector_text(raw_html: str, selector: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    candidate = soup.select_one(selector)
    if candidate is None:
        return ""
    for tag_name in BOILERPLATE_SELECTORS:
        for tag in candidate.find_all(tag_name):
            tag.decompose()
    text = candidate.get_text("\n", strip=True)
    return clean_article_text(text)


def extract_article_dom_text(raw_html: str) -> str:
    candidates: list[str] = []
    for selector in ARTICLE_BODY_SELECTORS:
        candidate_text = extract_selector_text(raw_html, selector)
        if candidate_text:
            candidates.append(candidate_text)
    if not candidates:
        return ""
    return max(candidates, key=len)


def discover_candidate_urls(raw_html: str, fallback_url: str) -> list[str]:
    soup = BeautifulSoup(raw_html, "html.parser")
    candidates: list[str] = [strip_tracking_parameters(fallback_url)]
    for selector, attribute in (
        ("link[rel='canonical']", "href"),
        ("link[rel='amphtml']", "href"),
        ("meta[property='og:url']", "content"),
        ("meta[name='twitter:url']", "content"),
    ):
        tag = soup.select_one(selector)
        if tag is None:
            continue
        value = tag.get(attribute)
        if not value:
            continue
        candidates.append(urljoin(fallback_url, value.strip()))

    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        normalized = strip_tracking_parameters(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def extract_html_text(raw_html: str, url: str) -> str:
    candidate_urls = discover_candidate_urls(raw_html, url)
    extracted_texts: list[str] = []
    for candidate_url in candidate_urls:
        extracted = trafilatura.extract(
            raw_html,
            url=candidate_url,
            include_comments=False,
            include_tables=True,
        )
        if extracted:
            normalized = clean_article_text(extracted.strip())
            if normalized:
                extracted_texts.append(normalized)

    if is_article_host(url):
        jsonld_text = extract_jsonld_article_body(raw_html)
        if jsonld_text:
            extracted_texts.append(jsonld_text)
        dom_text = extract_article_dom_text(raw_html)
        if dom_text:
            extracted_texts.append(dom_text)

    if extracted_texts:
        return max(extracted_texts, key=len).strip()

    soup = BeautifulSoup(raw_html, "html.parser")
    return clean_article_text(soup.get_text("\n", strip=True))


def _make_session() -> requests.Session:
    """Create a requests Session with automatic retry on transient errors."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET", "HEAD"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _extra_headers_raw = os.environ.get("KB_HTTP_HEADERS", "")
    if _extra_headers_raw:
        import json as _json
        try:
            session.headers.update(_json.loads(_extra_headers_raw))
        except Exception:
            pass
    bearer = os.environ.get("KB_HTTP_BEARER_TOKEN", "")
    if bearer:
        session.headers["Authorization"] = f"Bearer {bearer}"
    return session


def fetch_url(url: str) -> tuple[bytes, str | None, str, str, str]:
    session = _make_session()
    response = session.get(url, timeout=30, headers={"User-Agent": "living-kb-cli/0.1"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    filename = Path(urlparse(url).path).name or "downloaded"
    return (
        response.content,
        response.text if "text" in content_type or "html" in content_type else None,
        content_type,
        filename,
        response.url,
    )


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
            raw_bytes, maybe_text, content_type, filename, resolved_url = fetch_url(candidate)
            return raw_bytes, maybe_text, content_type, filename, resolved_url
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
            raw_bytes, maybe_text, content_type, filename, resolved_url = fetch_url(item)
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
            normalized = extract_html_text(maybe_text, resolved_url)
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
