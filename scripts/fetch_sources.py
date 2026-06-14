from __future__ import annotations

import argparse
import json
import mimetypes
import hashlib
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
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
HTTP_SESSION: requests.Session | None = None


def get_session() -> requests.Session:
    global HTTP_SESSION
    if HTTP_SESSION is not None:
        return HTTP_SESSION
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.0,
        status_forcelist=sorted(RETRYABLE_STATUSES),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    HTTP_SESSION = session
    return session


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


def sanitize_utf8_text(text: str) -> str:
    return text.encode("utf-8", "replace").decode("utf-8")


def strip_tracking_parameters(url: str) -> str:
    parsed = urlsplit(url)
    filtered_query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in TRACKING_QUERY_PARAMS:
            continue
        if key.startswith(TRACKING_QUERY_PREFIXES):
            continue
        filtered_query.append((key, value))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered_query), parsed.fragment)
    )


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


def fetch_url(url: str) -> tuple[bytes, str | None, str, str, str]:
    response = get_session().get(url, timeout=30, headers={"User-Agent": "agkb/0.1"})
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


def extract_html_bibliographic_metadata(raw_html: str) -> dict:
    meta = {"author": None, "journal": None, "year": None, "doi": None}
    try:
        soup = BeautifulSoup(raw_html, "html.parser")

        # DOI
        doi_meta = (
            soup.find("meta", attrs={"name": "citation_doi"})
            or soup.find("meta", attrs={"property": "citation_doi"})
            or soup.find("meta", attrs={"name": "dc.identifier"})
            or soup.find("meta", attrs={"name": "dc.identifier.doi"})
        )
        if doi_meta and doi_meta.get("content"):
            meta["doi"] = doi_meta.get("content").strip()

        # Title/Journal
        journal_meta = (
            soup.find("meta", attrs={"name": "citation_journal_title"})
            or soup.find("meta", attrs={"name": "citation_publisher"})
            or soup.find("meta", attrs={"name": "dc.publisher"})
        )
        if journal_meta and journal_meta.get("content"):
            meta["journal"] = journal_meta.get("content").strip()

        # Author
        author_metas = soup.find_all("meta", attrs={"name": "citation_author"}) or soup.find_all(
            "meta", attrs={"name": "dc.creator"}
        )
        if author_metas:
            authors = [am.get("content").strip() for am in author_metas if am.get("content")]
            if authors:
                meta["author"] = ", ".join(authors)

        # Year
        date_meta = (
            soup.find("meta", attrs={"name": "citation_date"})
            or soup.find("meta", attrs={"name": "citation_publication_date"})
            or soup.find("meta", attrs={"name": "dc.date"})
            or soup.find("meta", attrs={"name": "dc.date.issued"})
        )
        if date_meta and date_meta.get("content"):
            date_str = date_meta.get("content").strip()
            year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
            if year_match:
                meta["year"] = int(year_match.group(0))
    except Exception:
        pass
    return meta


def extract_pdf_bibliographic_metadata(pdf_path: Path) -> dict:
    meta = {"author": None, "journal": None, "year": None, "doi": None}
    try:
        reader = PdfReader(str(pdf_path))
        pdf_meta = reader.metadata
        if pdf_meta:
            if pdf_meta.author:
                meta["author"] = pdf_meta.author
            creation_date = pdf_meta.get("/CreationDate")
            if creation_date:
                year_match = re.search(r"\b(19|20)\d{2}\b", creation_date)
                if year_match:
                    meta["year"] = int(year_match.group(0))
    except Exception:
        pass
    return meta


def extract_doi_fallback(text: str) -> str | None:
    match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def segment_source(
    normalized_content: str,
    source_kind: str,
    source_id: str,
    is_pdf: bool = False,
    pdf_path: Path | None = None,
) -> list[dict]:
    segments = []
    content_len = len(normalized_content)

    # 1. Determine structural type
    struct_type = "generic"
    k = str(source_kind or "").lower()
    if k in ("github-repo-snapshot", "github-file", "github_repo_snapshot") or "github.com/" in k:
        struct_type = "repos"
    elif (
        "transcript" in source_id
        or "transcript" in normalized_content.lower()[:1000]
        or re.search(r"(?m)^speaker:|^\[speaker\]", normalized_content, re.IGNORECASE)
    ):
        struct_type = "transcripts"
    elif is_pdf or k in ("paper-pdf", "arxiv-paper"):
        struct_type = "papers"
    elif re.search(r"(?m)^#+\s+(part|chapter)\b", normalized_content, re.IGNORECASE):
        struct_type = "books"

    # 2. Segment based on structural type
    if struct_type == "repos":
        # Segment by files (e.g. "### README.md", "### scripts/kb.py")
        matches = list(re.finditer(r"(?m)^###\s+([a-zA-Z0-9_\-\./]+)\s*$", normalized_content))
        for i, match in enumerate(matches):
            filename = match.group(1)
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else content_len
            file_content = normalized_content[start_pos:end_pos]
            seg_id = f"{source_id}-file-{slugify(filename)}"
            segments.append(
                {
                    "id": seg_id,
                    "type": "file",
                    "title": f"file: {filename}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(file_content.encode("utf-8")).hexdigest()[:10],
                }
            )

            # Look for sub-elements: class, function, symbol inside
            sub_matches = re.finditer(
                r"(?m)(?:class\s+([a-zA-Z0-9_]+)|def\s+([a-zA-Z0-9_]+)\(|function\s+([a-zA-Z0-9_]+)\()",
                file_content,
            )
            for sub_match in sub_matches:
                class_name = sub_match.group(1)
                func_name = sub_match.group(2) or sub_match.group(3)
                sub_type = "class" if class_name else "function"
                sub_name = class_name if class_name else func_name
                sub_start = start_pos + sub_match.start()
                sub_end = min(sub_start + 2000, end_pos)
                sub_content = normalized_content[sub_start:sub_end]
                sub_id = f"{source_id}-{sub_type}-{slugify(sub_name)}"
                segments.append(
                    {
                        "id": sub_id,
                        "type": sub_type,
                        "title": f"{sub_type}: {sub_name}",
                        "start_char": sub_start,
                        "end_char": sub_end,
                        "content_hash": hashlib.sha256(sub_content.encode("utf-8")).hexdigest()[
                            :10
                        ],
                    }
                )

    elif struct_type == "transcripts":
        # Segment by speaker, topic, decision, action item
        matches = list(re.finditer(r"(?m)^([a-zA-Z0-9\s]+):\s+(.+)$", normalized_content))
        for i, match in enumerate(matches):
            speaker = match.group(1).strip()
            if len(speaker) > 40 or "\n" in speaker or "#" in speaker:
                continue
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else content_len
            speaker_content = normalized_content[start_pos:end_pos]
            seg_id = f"{source_id}-speaker-{slugify(speaker)}-{i}"
            segments.append(
                {
                    "id": seg_id,
                    "type": "speaker",
                    "title": f"speaker: {speaker}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(speaker_content.encode("utf-8")).hexdigest()[
                        :10
                    ],
                }
            )

        action_matches = re.finditer(
            r"(?m)(?i)^([*-]\s+)?(decision|action item):\s*(.+)$", normalized_content
        )
        for idx, match in enumerate(action_matches):
            item_text = match.group(3).strip()
            item_type = match.group(2).lower().replace(" ", "_")
            start_pos = match.start()
            end_pos = start_pos + len(match.group(0))
            seg_id = f"{source_id}-{item_type}-{idx}"
            segments.append(
                {
                    "id": seg_id,
                    "type": item_type,
                    "title": f"{item_type}: {item_text[:30]}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:10],
                }
            )

    elif struct_type == "books":
        # Segment by part, chapter, section, paragraph
        headings = list(re.finditer(r"(?m)^(#+)\s+(.+)$", normalized_content))
        for i, h in enumerate(headings):
            title = h.group(2).strip()
            start_pos = h.start()
            end_pos = headings[i + 1].start() if i + 1 < len(headings) else content_len
            h_content = normalized_content[start_pos:end_pos]
            t_lower = title.lower()
            h_type = (
                "part" if "part" in t_lower else ("chapter" if "chapter" in t_lower else "section")
            )
            seg_id = f"{source_id}-{h_type}-{slugify(title)}"
            segments.append(
                {
                    "id": seg_id,
                    "type": h_type,
                    "title": f"{h_type}: {title}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(h_content.encode("utf-8")).hexdigest()[:10],
                }
            )

        paragraphs = list(re.finditer(r"\n\n([^\n]+)", normalized_content))
        for idx, p in enumerate(paragraphs):
            p_text = p.group(1).strip()
            if len(p_text) < 100:
                continue
            start_pos = p.start(1)
            end_pos = p.end(1)
            p_hash = hashlib.sha256(p_text.encode("utf-8")).hexdigest()[:10]
            seg_id = f"{source_id}-para-{p_hash}"
            segments.append(
                {
                    "id": seg_id,
                    "type": "paragraph",
                    "title": f"paragraph {idx}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": p_hash,
                }
            )

    else:
        # PDFs & papers: abstract, method, results, limitations, references OR page, heading, table, figure, caption
        if is_pdf and pdf_path and pdf_path.exists():
            try:
                reader = PdfReader(str(pdf_path))
                current_offset = 0
                for idx, page in enumerate(reader.pages):
                    page_num = idx + 1
                    page_text = page.extract_text() or ""
                    start_pos = normalized_content.find(page_text[:100], current_offset)
                    if start_pos == -1:
                        start_pos = normalized_content.find(page_text[:30], current_offset)
                    if start_pos == -1:
                        start_pos = current_offset
                    end_pos = normalized_content.find(page_text[-100:], start_pos)
                    if end_pos == -1:
                        end_pos = start_pos + len(page_text)
                    else:
                        end_pos += 100
                    end_pos = min(end_pos, content_len)
                    current_offset = end_pos
                    p_content = normalized_content[start_pos:end_pos]
                    seg_id = f"{source_id}-page-{page_num}"
                    segments.append(
                        {
                            "id": seg_id,
                            "type": "page",
                            "title": f"Page {page_num}",
                            "start_char": start_pos,
                            "end_char": end_pos,
                            "content_hash": hashlib.sha256(p_content.encode("utf-8")).hexdigest()[
                                :10
                            ],
                        }
                    )
            except Exception:
                pass

        # Headings
        headings = list(re.finditer(r"(?m)^(#+)\s+(.+)$", normalized_content))
        for i, h in enumerate(headings):
            title = h.group(2).strip()
            start_pos = h.start()
            end_pos = headings[i + 1].start() if i + 1 < len(headings) else content_len
            h_content = normalized_content[start_pos:end_pos]
            t_lower = title.lower()
            if "abstract" in t_lower:
                h_type = "abstract"
            elif any(w in t_lower for w in ("method", "methodology", "approach", "implementation")):
                h_type = "method"
            elif any(w in t_lower for w in ("result", "evaluation", "experiment", "finding")):
                h_type = "results"
            elif any(w in t_lower for w in ("limitation", "discussion", "future work")):
                h_type = "limitations"
            elif any(w in t_lower for w in ("reference", "bibliography")):
                h_type = "references"
            else:
                h_type = "heading"

            seg_id = f"{source_id}-heading-{slugify(title)}"
            segments.append(
                {
                    "id": seg_id,
                    "type": h_type,
                    "title": f"{h_type}: {title}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(h_content.encode("utf-8")).hexdigest()[:10],
                }
            )

        # Tables
        tables = list(re.finditer(r"(?s)\n\n(\|.+?\|\n\n|<table>.+?</table>)", normalized_content))
        for idx, t in enumerate(tables):
            t_text = t.group(1).strip()
            start_pos = t.start(1)
            end_pos = t.end(1)
            seg_id = f"{source_id}-table-{idx}"
            segments.append(
                {
                    "id": seg_id,
                    "type": "table",
                    "title": f"Table {idx + 1}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(t_text.encode("utf-8")).hexdigest()[:10],
                }
            )

        # Figures
        figures = list(
            re.finditer(r"(?i)\b(figure|fig\.)\s+\d+[:\s\.]+(.*?)(?=\n\n|\Z)", normalized_content)
        )
        for idx, f in enumerate(figures):
            f_text = f.group(0).strip()
            start_pos = f.start()
            end_pos = f.end()
            seg_id = f"{source_id}-figure-{idx}"
            segments.append(
                {
                    "id": seg_id,
                    "type": "figure",
                    "title": f"Figure {idx + 1}",
                    "start_char": start_pos,
                    "end_char": end_pos,
                    "content_hash": hashlib.sha256(f_text.encode("utf-8")).hexdigest()[:10],
                }
            )
            caption = f.group(2).strip()
            if caption:
                c_id = f"{source_id}-caption-{idx}"
                segments.append(
                    {
                        "id": c_id,
                        "type": "caption",
                        "title": f"Caption {idx + 1}",
                        "start_char": f.start(2),
                        "end_char": f.end(2),
                        "content_hash": hashlib.sha256(caption.encode("utf-8")).hexdigest()[:10],
                    }
                )

    return segments


def process_large_source(
    normalized_content: str,
    source_dir: Path,
    source_id: str,
    is_pdf: bool,
    pdf_path: Path | None = None,
    raw_html: str | None = None,
    source_kind: str | None = None,
) -> dict | None:
    if len(normalized_content) <= 10000:
        return None

    # 1. Segment/chunk
    chunks = []
    start = 0
    chunk_size = 10000
    overlap = 1000
    step = chunk_size - overlap  # 9000

    while start < len(normalized_content):
        end = start + chunk_size
        chunk_data = normalized_content[start:end]
        chunks.append(chunk_data)
        if end >= len(normalized_content):
            break
        start += step

    page_level_chunks = []
    for i, chunk in enumerate(chunks, 1):
        part_filename = f"{source_id}-part{i}.md"
        part_path = source_dir / part_filename
        part_path.write_text(chunk, encoding="utf-8")
        page_level_chunks.append({"path": str(part_path.relative_to(ROOT)), "length": len(chunk)})

    # 2. Gather diagnostics
    page_count = None
    text_extraction_coverage = 100.0
    figures_count = 0
    figures_positions = []
    tables_count = 0
    tables_positions = []

    author = None
    journal = None
    year = None
    doi = None

    if is_pdf and pdf_path and pdf_path.exists():
        try:
            reader = PdfReader(str(pdf_path))
            page_count = len(reader.pages)
            successful_pages = 0
            for idx, page in enumerate(reader.pages):
                page_num = idx + 1
                page_text = page.extract_text() or ""
                if page_text.strip():
                    successful_pages += 1

                # Count images/figures
                try:
                    num_images = len(page.images)
                except Exception:
                    num_images = 0
                if num_images > 0:
                    figures_count += num_images
                    figures_positions.extend([page_num] * num_images)

                # Search for tables in text
                table_matches = re.findall(r"(?i)\btable\s+\d+", page_text)
                if table_matches:
                    tables_count += len(table_matches)
                    tables_positions.extend([page_num] * len(table_matches))

            text_extraction_coverage = (
                (successful_pages / page_count) * 100.0 if page_count > 0 else 0.0
            )

            # PDF metadata
            pdf_meta = extract_pdf_bibliographic_metadata(pdf_path)
            author = pdf_meta["author"]
            journal = pdf_meta["journal"]
            year = pdf_meta["year"]
            doi = pdf_meta["doi"]
        except Exception:
            pass

    else:
        page_count = None
        text_extraction_coverage = 100.0 if normalized_content.strip() else 0.0

        if raw_html:
            try:
                soup = BeautifulSoup(raw_html, "html.parser")

                # Count figures (img and figure tags)
                images = soup.find_all(["img", "figure"])
                figures_count = len(images)
                for img in images:
                    pos = raw_html.find(str(img)[:100])
                    if pos != -1:
                        figures_positions.append(pos)

                # Count tables (table tags)
                tables = soup.find_all("table")
                tables_count = len(tables)
                for tbl in tables:
                    pos = raw_html.find(str(tbl)[:100])
                    if pos != -1:
                        tables_positions.append(pos)

                # Extract bibliographic metadata from HTML meta tags
                html_meta = extract_html_bibliographic_metadata(raw_html)
                author = html_meta["author"]
                journal = html_meta["journal"]
                year = html_meta["year"]
                doi = html_meta["doi"]
            except Exception:
                pass

    # DOI search in text as fallback
    if not doi:
        doi = extract_doi_fallback(normalized_content)

    # Build segments
    segments = segment_source(
        normalized_content=normalized_content,
        source_kind=source_kind,
        source_id=source_id,
        is_pdf=is_pdf,
        pdf_path=pdf_path,
    )

    sections_detected = [
        s["title"].split(": ", 1)[-1]
        for s in segments
        if s["type"]
        in (
            "heading",
            "abstract",
            "method",
            "results",
            "limitations",
            "references",
            "part",
            "chapter",
            "section",
        )
    ]
    tables_detected = [
        {"id": s["id"], "title": s["title"]} for s in segments if s["type"] == "table"
    ]
    figures_detected = [
        {"id": s["id"], "title": s["title"]} for s in segments if s["type"] == "figure"
    ]

    manifest = {
        "page_count": page_count,
        "text_extraction_coverage": text_extraction_coverage,
        "page_level_chunks": page_level_chunks,
        "figures_tables_status": {
            "figures": {"count": figures_count, "positions": figures_positions},
            "tables": {"count": tables_count, "positions": tables_positions},
        },
        "bibliographic_metadata": {"author": author, "journal": journal, "year": year, "doi": doi},
        # P1.1 and P1.2 required fields
        "sections_detected": sections_detected,
        "tables_detected": tables_detected,
        "figures_detected": figures_detected,
        "ocr_used": False,
        "ocr_confidence": None,
        "extraction_tool": "pypdf" if is_pdf else "trafilatura",
        "extraction_warnings": [],
        "segments": segments,
        "omitted_content": [],
    }

    manifest_path = source_dir / "large_source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


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
    maybe_text: str | None = None
    is_pdf_source = False
    pdf_path = None
    raw_html_content = None
    suffix = ""

    if is_url(item):
        if is_arxiv_url(item):
            raw_bytes, maybe_text, content_type, filename, resolved_url = fetch_arxiv_article(item)
        else:
            raw_bytes, maybe_text, content_type, filename, resolved_url = fetch_url(item)
        original_bytes = raw_bytes
        suffix = (
            Path(filename).suffix or mimetypes.guess_extension(content_type.split(";")[0]) or ".bin"
        )
        original_path = source_dir / f"original{suffix}"
        original_path.write_bytes(raw_bytes)
        metadata.update(
            {
                "kind": "url",
                "content_type": content_type,
                "original_path": str(original_path.relative_to(ROOT)),
                "resolved_url": resolved_url,
            }
        )

        normalized = ""
        is_pdf_source = "pdf" in content_type or suffix.lower() == ".pdf"
        if is_pdf_source:
            normalized = extract_pdf_text(original_path)
            pdf_path = original_path
        elif maybe_text is not None:
            normalized = extract_html_text(maybe_text, resolved_url)
            raw_html_content = maybe_text
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
        metadata.update(
            {
                "kind": "file",
                "content_type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
                "original_path": str(copied_path.relative_to(ROOT)),
            }
        )
        is_pdf_source = suffix == ".pdf"
        if is_pdf_source:
            normalized = extract_pdf_text(copied_path)
            pdf_path = copied_path
        else:
            normalized = path.read_text(encoding="utf-8", errors="ignore")
            if suffix in (".html", ".htm"):
                raw_html_content = normalized

    normalized_content = sanitize_utf8_text(normalized).strip() + "\n"
    original_content = (
        original_bytes.decode("utf-8", errors="replace")
        if isinstance(original_bytes, bytes)
        else original_bytes
    )
    if normalized_content.strip() != original_content.strip():
        normalized_path = source_dir / "normalized.md"
        normalized_path.write_text(normalized_content, encoding="utf-8")
        metadata["normalized_path"] = str(normalized_path.relative_to(ROOT))

    # Segment and write large source manifest if content exceeds 10,000 chars
    manifest = process_large_source(
        normalized_content=normalized_content,
        source_dir=source_dir,
        source_id=source_id,
        is_pdf=is_pdf_source,
        pdf_path=pdf_path,
        raw_html=raw_html_content,
        source_kind=metadata.get("kind"),
    )
    if manifest:
        metadata["large_source_manifest_path"] = str(
            (source_dir / "large_source_manifest.json").relative_to(ROOT)
        )

    metadata["title_guess"] = slugify(item).replace("_", " ").title()
    metadata["content_hash"] = content_hash(original_bytes)
    metadata["last_checked_at"] = now_stamp()
    (source_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
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
    parser.add_argument(
        "--input", required=True, help="Path to a newline-delimited list of URLs or local paths"
    )
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
