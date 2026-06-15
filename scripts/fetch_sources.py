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
    response = get_session().get(url, timeout=30, headers={"User-Agent": "K-Ops/0.1"})
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


# ---------------------------------------------------------------------------
# A7: v2 segment node helpers
# ---------------------------------------------------------------------------


def _to_anchor(title: str) -> str:
    """Convert a title to a Markdown-safe heading anchor (max 60 chars)."""
    s = title.lower().strip()
    s = re.sub(r"^[a-z]+:\s*", "", s)  # strip "type: " prefix
    s = re.sub(r"[^a-z0-9 \-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s).strip("-")
    if not s or not s[0].isalnum():
        s = "node-" + s
    return s[:60]


def _make_node(
    node_id: str,
    type_: str,
    title: str,
    start_char: int,
    end_char: int,
    content: str,
    level: int = 1,
    parent_id: str | None = None,
    order: int = 0,
    page_start: int | None = None,
    page_end: int | None = None,
    extraction_method: str = "heuristic",
    confidence: str = "medium",
    warnings: list | None = None,
) -> dict:
    return {
        "node_id": node_id,
        "parent_id": parent_id,
        "order": order,
        "level": level,
        "type": type_,
        "title": title,
        "anchor": _to_anchor(title),
        "start_char": start_char,
        "end_char": end_char,
        "page_start": page_start,
        "page_end": page_end,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest()[:10],
        "extraction_method": extraction_method,
        "confidence": confidence,
        "warnings": warnings or [],
        "source_note_heading": None,
    }


def _dedup_node_ids(nodes: list[dict]) -> list[dict]:
    """Append -2, -3, … suffix to any repeated node_id values."""
    seen: dict[str, int] = {}
    for node in nodes:
        nid = node["node_id"]
        if nid in seen:
            seen[nid] += 1
            node["node_id"] = f"{nid}-{seen[nid]}"
            node["warnings"] = list(node.get("warnings") or []) + ["deduplicated-node-id"]
        else:
            seen[nid] = 0
    return nodes


def _heading_type(title_lower: str) -> str:
    if "abstract" in title_lower:
        return "abstract"
    if any(w in title_lower for w in ("method", "methodology", "approach", "implementation")):
        return "method_section"
    if any(w in title_lower for w in ("result", "evaluation", "experiment", "finding")):
        return "results"
    if any(w in title_lower for w in ("limitation", "discussion", "future")):
        return "limitations"
    if any(w in title_lower for w in ("reference", "bibliography")):
        return "references"
    if re.search(r"\b(appendix|annex)\b", title_lower):
        return "appendix"
    if re.search(r"\b(glossary)\b", title_lower):
        return "glossary"
    return "heading"


def _segment_by_md_headings(
    normalized_content: str,
    source_id: str,
    extraction_method: str = "md-heading",
    confidence: str = "medium",
    extra_warnings: list | None = None,
) -> list[dict]:
    """Build v2 nodes from ATX headings in normalized_content."""
    content_len = len(normalized_content)
    headings = list(re.finditer(r"(?m)^(#+)\s+(.+)$", normalized_content))
    nodes: list[dict] = []

    if not headings:
        return nodes

    root_id = f"{source_id}-doc-root"
    root_node = _make_node(
        root_id,
        "document",
        source_id,
        0,
        content_len,
        normalized_content,
        level=0,
        parent_id=None,
        order=0,
        extraction_method=extraction_method,
        confidence=confidence,
        warnings=(extra_warnings or []) + ["heading-fallback-root"],
    )
    nodes.append(root_node)

    parent_stack: list[tuple[int, str]] = [(0, root_id)]
    for i, h in enumerate(headings):
        hashes = h.group(1)
        title = h.group(2).strip()
        hlevel = len(hashes)
        start_pos = h.start()
        end_pos = headings[i + 1].start() if i + 1 < len(headings) else content_len

        while len(parent_stack) > 1 and parent_stack[-1][0] >= hlevel:
            parent_stack.pop()
        parent_id_val = parent_stack[-1][1]

        h_type = _heading_type(title.lower())
        node_id = f"{source_id}-h{hlevel}-{slugify(title)}-{i}"
        node = _make_node(
            node_id,
            h_type,
            title,
            start_pos,
            end_pos,
            normalized_content[start_pos:end_pos],
            level=hlevel,
            parent_id=parent_id_val,
            order=i,
            extraction_method=extraction_method,
            confidence=confidence,
        )
        nodes.append(node)
        parent_stack.append((hlevel, node_id))

    return nodes


def segment_source(
    normalized_content: str,
    source_kind: str,
    source_id: str,
    is_pdf: bool = False,
    pdf_path: Path | None = None,
    raw_html: str | None = None,
) -> list[dict]:
    """Return a list of v2 segment nodes for normalized_content."""
    nodes: list[dict] = []
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
        seen_file_ids: dict[str, int] = {}
        for i, match in enumerate(matches):
            filename = match.group(1)
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else content_len
            file_content = normalized_content[start_pos:end_pos]
            base_id = f"{source_id}-file-{slugify(filename)}"
            if base_id in seen_file_ids:
                seen_file_ids[base_id] += 1
                node_id = f"{base_id}-{seen_file_ids[base_id]}"
            else:
                seen_file_ids[base_id] = 0
                node_id = base_id
            node = _make_node(
                node_id,
                "file",
                f"file: {filename}",
                start_pos,
                end_pos,
                file_content,
                level=1,
                parent_id=None,
                order=i,
                extraction_method="file-split",
                confidence="high",
            )
            nodes.append(node)

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
                sub_node = _make_node(
                    sub_id,
                    sub_type,
                    f"{sub_type}: {sub_name}",
                    sub_start,
                    sub_end,
                    sub_content,
                    level=2,
                    parent_id=node_id,
                    order=len(nodes),
                    extraction_method="heuristic",
                    confidence="medium",
                )
                nodes.append(sub_node)

    elif struct_type == "transcripts":
        # Segment by speaker, topic, decision, action item
        matches = list(re.finditer(r"(?m)^([a-zA-Z0-9\s]+):\s+(.+)$", normalized_content))
        last_speaker_id: str | None = None
        for i, match in enumerate(matches):
            speaker = match.group(1).strip()
            if len(speaker) > 40 or "\n" in speaker or "#" in speaker:
                continue
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else content_len
            speaker_content = normalized_content[start_pos:end_pos]
            seg_id = f"{source_id}-speaker-{slugify(speaker)}-{i}"
            node = _make_node(
                seg_id,
                "speaker",
                f"speaker: {speaker}",
                start_pos,
                end_pos,
                speaker_content,
                level=1,
                parent_id=None,
                order=i,
                extraction_method="heuristic",
                confidence="medium",
            )
            nodes.append(node)
            last_speaker_id = seg_id

        action_matches = re.finditer(
            r"(?m)(?i)^([*-]\s+)?(decision|action item):\s*(.+)$", normalized_content
        )
        for idx, match in enumerate(action_matches):
            item_text = match.group(3).strip()
            item_type = match.group(2).lower().replace(" ", "_")
            start_pos = match.start()
            end_pos = start_pos + len(match.group(0))
            seg_id = f"{source_id}-{item_type}-{idx}"
            node = _make_node(
                seg_id,
                item_type,
                f"{item_type}: {item_text[:30]}",
                start_pos,
                end_pos,
                match.group(0),
                level=2,
                parent_id=last_speaker_id,
                order=idx,
                extraction_method="heuristic",
                confidence="low",
            )
            nodes.append(node)

    elif struct_type == "books":
        # Segment by heading only (no paragraph-as-node)
        headings = list(re.finditer(r"(?m)^(#+)\s+(.+)$", normalized_content))
        parent_stack: list[tuple[int, str]] = [(0, None)]  # type: ignore[list-item]
        for i, h in enumerate(headings):
            title = h.group(2).strip()
            start_pos = h.start()
            end_pos = headings[i + 1].start() if i + 1 < len(headings) else content_len
            h_content = normalized_content[start_pos:end_pos]
            hlevel = len(h.group(1))
            t_lower = title.lower()
            if "part" in t_lower or "book" in t_lower:
                h_type = "part"
            elif "chapter" in t_lower:
                h_type = "chapter"
            elif re.search(r"\b(appendix|annex)\b", t_lower):
                h_type = "appendix"
            elif re.search(r"\b(glossary)\b", t_lower):
                h_type = "glossary"
            elif re.search(r"\b(index)\b", t_lower):
                h_type = "index"
            elif re.search(r"\b(reference|bibliography)\b", t_lower):
                h_type = "references"
            else:
                h_type = "section"

            while len(parent_stack) > 1 and parent_stack[-1][0] >= hlevel:
                parent_stack.pop()
            parent_id_val = parent_stack[-1][1]

            seg_id = f"{source_id}-{h_type}-{slugify(title)}-{i}"
            node = _make_node(
                seg_id,
                h_type,
                f"{h_type}: {title}",
                start_pos,
                end_pos,
                h_content,
                level=hlevel,
                parent_id=parent_id_val,
                order=i,
                extraction_method="md-heading",
                confidence="medium",
            )
            nodes.append(node)
            parent_stack.append((hlevel, seg_id))

    else:
        # Papers / PDFs / HTML / generic

        # --- HTML path: use BeautifulSoup heading hierarchy when raw_html available ---
        if raw_html and not is_pdf:
            try:
                soup = BeautifulSoup(raw_html, "html.parser")
                html_headings = soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
                if html_headings:
                    root_id = f"{source_id}-doc-root"
                    root_node = _make_node(
                        root_id,
                        "document",
                        source_id,
                        0,
                        content_len,
                        normalized_content,
                        level=0,
                        parent_id=None,
                        order=0,
                        extraction_method="html-headings",
                        confidence="high",
                    )
                    nodes.append(root_node)
                    parent_stack_html: list[tuple[int, str]] = [(0, root_id)]
                    for i, tag in enumerate(html_headings):
                        title = tag.get_text(strip=True)
                        hlevel = int(tag.name[1])
                        # Find title in normalized_content
                        start_pos = normalized_content.find(title)
                        if start_pos == -1:
                            # Try first 50 chars
                            start_pos = (
                                normalized_content.find(title[:50]) if len(title) > 50 else -1
                            )
                        if start_pos == -1:
                            conf = "low"
                            warns = ["html-heading-not-found-in-content"]
                            start_pos = 0
                        else:
                            conf = "high"
                            warns = []

                        end_pos = content_len  # will be fixed in next pass
                        while len(parent_stack_html) > 1 and parent_stack_html[-1][0] >= hlevel:
                            parent_stack_html.pop()
                        parent_id_val = parent_stack_html[-1][1]

                        h_type = _heading_type(title.lower())
                        node_id = f"{source_id}-h{hlevel}-{slugify(title)}-{i}"
                        node = _make_node(
                            node_id,
                            h_type,
                            title,
                            start_pos,
                            end_pos,
                            normalized_content[start_pos:end_pos],
                            level=hlevel,
                            parent_id=parent_id_val,
                            order=i,
                            extraction_method="html-headings",
                            confidence=conf,
                            warnings=warns,
                        )
                        nodes.append(node)
                        parent_stack_html.append((hlevel, node_id))

                    # Fix end_char: each node ends where the next same-or-lower-level node starts
                    for idx in range(1, len(nodes)):
                        cur = nodes[idx]
                        # Find next node at same or higher level (lower number = higher in hierarchy)
                        for j in range(idx + 1, len(nodes)):
                            nxt = nodes[j]
                            if nxt["level"] <= cur["level"] and nxt["level"] > 0:
                                cur["end_char"] = nxt["start_char"]
                                break

                    nodes = _dedup_node_ids(nodes)
                    return nodes
            except Exception:
                pass  # Fall through to heading regex

        # --- PDF outline path ---
        if is_pdf and pdf_path and pdf_path.exists():
            try:
                reader = PdfReader(str(pdf_path))
                outline = reader.outline
                total_pages = len(reader.pages)

                if outline and len(outline) >= 2:
                    # Flatten outline with depth tracking
                    def _process_outline(
                        items: list,
                        level: int = 1,
                        parent_id: str | None = None,
                        order_start: int = 0,
                    ) -> list[dict]:
                        result: list[dict] = []
                        order = order_start
                        for item in items:
                            if isinstance(item, list):
                                # Nested children — attach to last node
                                if result:
                                    sub_parent = result[-1]["node_id"]
                                else:
                                    sub_parent = parent_id
                                sub = _process_outline(item, level + 1, sub_parent, 0)
                                result.extend(sub)
                            else:
                                title = getattr(item, "title", None) or f"Section {order}"
                                try:
                                    page_num = reader.get_destination_page_number(item) + 1
                                except Exception:
                                    page_num = None

                                # Locate title in normalized_content
                                anchor_text = title[:50]
                                start_pos = normalized_content.find(anchor_text)
                                if start_pos == -1:
                                    conf = "low"
                                    warns = ["outline-title-not-found-in-text"]
                                    start_pos = 0
                                else:
                                    conf = "high"
                                    warns = []

                                node_id = f"{source_id}-outline-{slugify(title)}-{order}"
                                node = _make_node(
                                    node_id,
                                    "section",
                                    title,
                                    start_pos,
                                    content_len,  # end_char fixed after
                                    normalized_content[start_pos:content_len],
                                    level=level,
                                    parent_id=parent_id,
                                    order=order,
                                    page_start=page_num,
                                    page_end=None,
                                    extraction_method="pdf-outline",
                                    confidence=conf,
                                    warnings=warns,
                                )
                                result.append(node)
                                order += 1
                        return result

                    outline_nodes = _process_outline(outline)
                    if outline_nodes:
                        # Fix end_char between same-level siblings
                        for idx in range(len(outline_nodes) - 1):
                            if outline_nodes[idx]["level"] == outline_nodes[idx + 1]["level"]:
                                next_start = outline_nodes[idx + 1]["start_char"]
                                if next_start > outline_nodes[idx]["start_char"]:
                                    outline_nodes[idx]["end_char"] = next_start
                        # Fix page_end
                        for idx in range(len(outline_nodes)):
                            cur = outline_nodes[idx]
                            if cur["page_start"] is not None:
                                for j in range(idx + 1, len(outline_nodes)):
                                    nxt = outline_nodes[j]
                                    if (
                                        nxt["level"] <= cur["level"]
                                        and nxt["page_start"] is not None
                                    ):
                                        cur["page_end"] = nxt["page_start"] - 1
                                        break
                                if cur["page_end"] is None:
                                    cur["page_end"] = total_pages

                        outline_nodes = _dedup_node_ids(outline_nodes)
                        return outline_nodes
            except Exception:
                pass

        # --- Heading-regex path (PDF fallback or generic/papers without outline) ---
        heading_nodes = _segment_by_md_headings(
            normalized_content,
            source_id,
            extraction_method="md-heading",
            confidence="medium" if not is_pdf else "low",
            extra_warnings=["no-pdf-outline-fallback-to-headings"] if is_pdf else [],
        )
        if heading_nodes:
            nodes = _dedup_node_ids(heading_nodes)
            return nodes

        # --- Tables ---
        tables = list(re.finditer(r"(?s)\n\n(\|.+?\|\n\n|<table>.+?</table>)", normalized_content))
        for idx, t in enumerate(tables):
            t_text = t.group(1).strip()
            start_pos = t.start(1)
            end_pos = t.end(1)
            node_id = f"{source_id}-table-{idx}"
            node = _make_node(
                node_id,
                "table",
                f"Table {idx + 1}",
                start_pos,
                end_pos,
                t_text,
                level=1,
                parent_id=None,
                order=idx,
                extraction_method="heuristic",
                confidence="medium",
            )
            nodes.append(node)

        # --- Figures ---
        figures = list(
            re.finditer(r"(?i)\b(figure|fig\.)\s+\d+[:\s\.]+(.*?)(?=\n\n|\Z)", normalized_content)
        )
        for idx, f in enumerate(figures):
            f_text = f.group(0).strip()
            start_pos = f.start()
            end_pos = f.end()
            node_id = f"{source_id}-figure-{idx}"
            node = _make_node(
                node_id,
                "figure",
                f"Figure {idx + 1}",
                start_pos,
                end_pos,
                f_text,
                level=1,
                parent_id=None,
                order=idx,
                extraction_method="heuristic",
                confidence="medium",
            )
            nodes.append(node)
            caption = f.group(2).strip()
            if caption:
                c_id = f"{source_id}-caption-{idx}"
                cap_node = _make_node(
                    c_id,
                    "caption",
                    f"Caption {idx + 1}",
                    f.start(2),
                    f.end(2),
                    caption,
                    level=2,
                    parent_id=node_id,
                    order=idx,
                    extraction_method="heuristic",
                    confidence="medium",
                )
                nodes.append(cap_node)

    # --- Headingless long doc fallback ---
    if not nodes and content_len > 10000:
        root_id = f"{source_id}-doc-root"
        root_node = _make_node(
            root_id,
            "document",
            source_id,
            0,
            content_len,
            normalized_content,
            level=1,
            parent_id=None,
            order=0,
            extraction_method="heuristic",
            confidence="low",
            warnings=["no_structure_detected"],
        )
        nodes.append(root_node)

    return _dedup_node_ids(nodes)


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

    # Build segments (v2 nodes)
    nodes = segment_source(
        normalized_content=normalized_content,
        source_kind=source_kind,
        source_id=source_id,
        is_pdf=is_pdf,
        pdf_path=pdf_path,
        raw_html=raw_html,
    )

    # Collect extraction warnings from nodes (low-confidence signals)
    extraction_warnings: list[str] = []
    for n in nodes:
        for w in n.get("warnings") or []:
            if w not in extraction_warnings:
                extraction_warnings.append(w)
    if not nodes and len(normalized_content) > 10000:
        extraction_warnings.append("no_structure_detected")

    _SECTION_TYPES = {
        "heading",
        "abstract",
        "method_section",
        "results",
        "limitations",
        "references",
        "part",
        "chapter",
        "section",
        "appendix",
        "glossary",
    }
    sections_detected = [
        n["title"].split(": ", 1)[-1] for n in nodes if n["type"] in _SECTION_TYPES
    ]
    tables_detected = [
        {"id": n["node_id"], "title": n["title"]} for n in nodes if n["type"] == "table"
    ]
    figures_detected = [
        {"id": n["node_id"], "title": n["title"]} for n in nodes if n["type"] == "figure"
    ]

    manifest = {
        "large_source_manifest_version": 2,
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
        "extraction_warnings": extraction_warnings,
        "nodes": nodes,
        "segments": nodes,  # backward-compat alias
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

    # Prompt-injection heuristic scan — flag suspicious content for human review.
    # These patterns match common injection signatures; detection does NOT auto-reject the
    # source. The ingest-sources step should set evidence_strength: adversarial if confirmed.
    _INJECTION_PATTERNS = [
        re.compile(
            r"^\s*ignore\s+(previous|all|prior)\s+instructions?", re.IGNORECASE | re.MULTILINE
        ),
        re.compile(r"^\s*disregard\s+(the\s+)?(system\s+)?prompt", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*you\s+are\s+now\s+", re.IGNORECASE | re.MULTILINE),
        re.compile(
            r"^\s*act\s+as\s+(a\s+)?(?:new|different|unrestricted)", re.IGNORECASE | re.MULTILINE
        ),
        re.compile(r"^\s*</?SYSTEM>", re.IGNORECASE | re.MULTILINE),
        re.compile(r"^\s*###\s*(?:system|instruction|override)\b", re.IGNORECASE | re.MULTILINE),
        re.compile(
            r"^\s*forget\s+everything\s+(you\s+)?(have\s+)?learned", re.IGNORECASE | re.MULTILINE
        ),
        re.compile(r"^\s*jailbreak\b", re.IGNORECASE | re.MULTILINE),
    ]
    matched_patterns: list[str] = []
    for pat in _INJECTION_PATTERNS:
        m = pat.search(normalized_content)
        if m:
            matched_patterns.append(m.group(0).strip()[:120])
    if matched_patterns:
        import sys

        print(
            f"WARNING: adversarial_hint detected in source {source_id} — "
            f"{len(matched_patterns)} injection-like pattern(s) found. "
            "Set evidence_strength: adversarial in the source summary if confirmed.",
            file=sys.stderr,
        )
        metadata["adversarial_hint"] = True
        metadata["adversarial_patterns_found"] = matched_patterns

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
