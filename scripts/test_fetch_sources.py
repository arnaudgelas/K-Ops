from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "medium_substack_article.html"


def main() -> None:
    sys.path.append(str(ROOT / "scripts"))
    from fetch_sources import extract_html_text, strip_tracking_parameters  # noqa: WPS433

    html = FIXTURE_PATH.read_text(encoding="utf-8")
    extracted = extract_html_text(html, "https://medium.com/example/story?utm_source=newsletter&fbclid=abc123")

    expected_lines = [
        "Real article title",
        "Real article body paragraph one.",
        "Real article body paragraph two.",
    ]
    for line in expected_lines:
        if line not in extracted:
            raise AssertionError(f"Missing expected article content: {line!r}\nExtracted:\n{extracted}")

    for banned in ("Subscribe", "Sign in", "Share", "Read more from the author"):
        if banned in extracted:
            raise AssertionError(f"Unexpected boilerplate in extraction: {banned!r}\nExtracted:\n{extracted}")

    canonical = strip_tracking_parameters("https://medium.com/example/story?utm_source=newsletter&fbclid=abc123")
    expected_canonical = "https://medium.com/example/story"
    if canonical != expected_canonical:
        raise AssertionError(f"Canonical URL mismatch: {canonical!r} != {expected_canonical!r}")

    print("fetch_sources regression passed")


if __name__ == "__main__":
    main()
