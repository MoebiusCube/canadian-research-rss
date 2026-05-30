#!/usr/bin/env python3
"""
Generate an RSS feed of recent academic research by Canadian-affiliated scholars
or research about Canada.

Data source: OpenAlex API
Output: docs/feed.xml

Repository setup:
- Put this file at the root of your GitHub repository.
- Put requirements.txt at the root.
- Put update-feed.yml in .github/workflows/
- Enable GitHub Pages using the /docs folder.

Optional:
- Set OPENALEX_MAILTO as a GitHub Actions repository variable or secret.
"""

from __future__ import annotations

import html
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from feedgen.feed import FeedGenerator


# ----------------------------
# Configuration
# ----------------------------

OPENALEX_API = "https://api.openalex.org/works"
OUTPUT_PATH = Path("docs/feed.xml")

FEED_TITLE = "Canadian Research Watch"
FEED_DESCRIPTION = (
    "Recent academic research by Canadian-affiliated scholars or about Canada, "
    "generated from OpenAlex metadata."
)

# Change this after GitHub Pages is enabled.
# Example: https://YOUR-USERNAME.github.io/canadian-research-rss/feed.xml
FEED_URL = os.getenv(
    "FEED_URL",
    "https://example.com/canadian-research-rss/feed.xml",
)

# OpenAlex asks high-volume users to include an email via the mailto parameter.
# You can set this in GitHub Actions as a repository variable/secret.
OPENALEX_MAILTO = os.getenv("OPENALEX_MAILTO", "")

DAYS_BACK = int(os.getenv("DAYS_BACK", "14"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "100"))

# To reduce false positives, raise this to 5 or 6.
MIN_SCORE = int(os.getenv("MIN_SCORE", "4"))

# OpenAlex page size. Max is commonly 200.
PER_PAGE = int(os.getenv("PER_PAGE", "100"))

# Publication types to include.
INCLUDED_TYPES = {
    "article",
    "review",
    "book-chapter",
    "report",
    "preprint",
}

CANADA_TERMS = [
    "canada",
    "canadian",
    "canadians",
    "alberta",
    "british columbia",
    "b.c.",
    "bc",
    "manitoba",
    "new brunswick",
    "newfoundland",
    "labrador",
    "nova scotia",
    "ontario",
    "prince edward island",
    "p.e.i.",
    "pei",
    "quebec",
    "québec",
    "saskatchewan",
    "northwest territories",
    "nunavut",
    "yukon",
    "toronto",
    "montreal",
    "montréal",
    "vancouver",
    "ottawa",
    "calgary",
    "edmonton",
    "winnipeg",
    "halifax",
    "regina",
    "saskatoon",
    "victoria",
    "hamilton",
    "waterloo",
    "london ontario",
    "first nations",
    "inuit",
    "métis",
    "metis",
    "indigenous peoples in canada",
    "statistics canada",
    "health canada",
    "canadian institutes of health research",
    "cihr",
    "sshrec",
    "sshrc",
    "nserc",
]

CANADIAN_INSTITUTION_TERMS = [
    "university of toronto",
    "university of british columbia",
    "ubc",
    "mcgill university",
    "university of alberta",
    "university of montreal",
    "université de montréal",
    "mcmaster university",
    "university of calgary",
    "university of ottawa",
    "university of waterloo",
    "western university",
    "queen's university",
    "simon fraser university",
    "sfu",
    "dalhousie university",
    "university of manitoba",
    "university of saskatchewan",
    "university of victoria",
    "york university",
    "carleton university",
    "concordia university",
    "toronto metropolitan university",
    "university of guelph",
    "memorial university",
    "university of windsor",
    "university of regina",
    "canadian institutes of health research",
    "statistics canada",
]


@dataclass
class FeedItem:
    title: str
    link: str
    guid: str
    published: date
    authors: str
    source: str
    summary: str
    score: int
    reasons: list[str]


# ----------------------------
# OpenAlex helpers
# ----------------------------

def inverted_index_to_text(index: dict[str, list[int]] | None) -> str:
    """Convert OpenAlex abstract inverted index into plain text."""
    if not index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, locs in index.items():
        for loc in locs:
            positions.append((loc, word))
    return " ".join(word for _, word in sorted(positions))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def text_contains_any(text: str, terms: list[str]) -> list[str]:
    text_l = f" {text.lower()} "
    found = []
    for term in terms:
        term_l = term.lower()
        if term_l in text_l:
            found.append(term)
    return found


def get_authors(work: dict[str, Any], limit: int = 8) -> str:
    names = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    if not names:
        return "Unknown author"
    if len(names) > limit:
        return ", ".join(names[:limit]) + " et al."
    return ", ".join(names)


def get_source(work: dict[str, Any]) -> str:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    return source.get("display_name") or "Unknown source"


def get_best_link(work: dict[str, Any]) -> str:
    doi = work.get("doi")
    if doi:
        return doi
    primary = work.get("primary_location") or {}
    if primary.get("landing_page_url"):
        return primary["landing_page_url"]
    ids = work.get("ids") or {}
    return ids.get("openalex") or work.get("id")


def is_canadian_affiliated(work: dict[str, Any]) -> bool:
    """Detect Canadian affiliation from structured country codes or raw strings."""
    for authorship in work.get("authorships", []):
        countries = authorship.get("countries") or []
        if "CA" in countries:
            return True

        for inst in authorship.get("institutions", []) or []:
            if inst.get("country_code") == "CA":
                return True
            display_name = normalize_text(inst.get("display_name")).lower()
            if any(term in display_name for term in CANADIAN_INSTITUTION_TERMS):
                return True

        for aff in authorship.get("raw_affiliation_strings", []) or []:
            aff_l = normalize_text(aff).lower()
            if "canada" in aff_l or any(term in aff_l for term in CANADIAN_INSTITUTION_TERMS):
                return True

    return False


def score_work(work: dict[str, Any]) -> tuple[int, list[str], str]:
    title = normalize_text(work.get("display_name"))
    abstract = normalize_text(inverted_index_to_text(work.get("abstract_inverted_index")))
    source = get_source(work)

    combined = f"{title} {abstract} {source}"

    score = 0
    reasons: list[str] = []

    if is_canadian_affiliated(work):
        score += 5
        reasons.append("Canadian-affiliated author or institution")

    title_matches = text_contains_any(title, CANADA_TERMS)
    if title_matches:
        score += 4
        reasons.append("Canada-related term in title: " + ", ".join(title_matches[:4]))

    abstract_matches = text_contains_any(abstract, CANADA_TERMS)
    if abstract_matches:
        score += 3
        reasons.append("Canada-related term in abstract: " + ", ".join(abstract_matches[:4]))

    source_matches = text_contains_any(source, CANADA_TERMS)
    if source_matches:
        score += 1
        reasons.append("Canada-related source title")

    institution_matches = text_contains_any(combined, CANADIAN_INSTITUTION_TERMS)
    if institution_matches:
        score += 2
        reasons.append("Canadian institution term detected")

    return score, reasons, abstract


def fetch_openalex_works() -> list[dict[str, Any]]:
    from_date = (datetime.now(timezone.utc).date() - timedelta(days=DAYS_BACK)).isoformat()

    # First query: Canadian-affiliated scholarship.
    # Second query: works that mention Canada-related terms, because not all Canada research
    # has Canadian-affiliated authors.
    queries = [
        {
            "filter": f"from_publication_date:{from_date},authorships.institutions.country_code:CA",
            "sort": "publication_date:desc",
        },
        {
            "filter": f"from_publication_date:{from_date}",
            "search": "Canada Canadian Indigenous Inuit Métis First Nations provinces territories",
            "sort": "publication_date:desc",
        },
    ]

    all_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for query in queries:
        cursor = "*"
        for _ in range(5):  # Up to 5 pages per query.
            params = {
                **query,
                "per-page": PER_PAGE,
                "cursor": cursor,
            }
            if OPENALEX_MAILTO:
                params["mailto"] = OPENALEX_MAILTO

            url = OPENALEX_API + "?" + urlencode(params)
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()

            for work in data.get("results", []):
                work_id = work.get("id")
                if work_id and work_id not in seen_ids:
                    seen_ids.add(work_id)
                    all_results.append(work)

            next_cursor = (data.get("meta") or {}).get("next_cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

            # Be polite to the API.
            time.sleep(0.2)

    return all_results


def make_feed_items(works: list[dict[str, Any]]) -> list[FeedItem]:
    items: list[FeedItem] = []
    seen_guid: set[str] = set()

    for work in works:
        work_type = work.get("type")
        if work_type and work_type not in INCLUDED_TYPES:
            continue

        title = normalize_text(work.get("display_name"))
        if not title:
            continue

        score, reasons, abstract = score_work(work)
        if score < MIN_SCORE:
            continue

        link = get_best_link(work)
        if not link:
            continue

        guid = work.get("doi") or work.get("id") or link
        if guid in seen_guid:
            continue
        seen_guid.add(guid)

        pub_date_raw = work.get("publication_date")
        try:
            published = datetime.strptime(pub_date_raw, "%Y-%m-%d").date()
        except Exception:
            published = datetime.now(timezone.utc).date()

        authors = get_authors(work)
        source = get_source(work)

        short_abstract = abstract[:900].rsplit(" ", 1)[0] + "..." if len(abstract) > 900 else abstract
        reason_text = "; ".join(reasons) if reasons else "Matched Canadian relevance filters"

        summary = (
            f"<p><strong>Authors:</strong> {html.escape(authors)}</p>"
            f"<p><strong>Source:</strong> {html.escape(source)}</p>"
            f"<p><strong>Why included:</strong> {html.escape(reason_text)}</p>"
        )
        if short_abstract:
            summary += f"<p><strong>Abstract:</strong> {html.escape(short_abstract)}</p>"

        items.append(
            FeedItem(
                title=title,
                link=link,
                guid=guid,
                published=published,
                authors=authors,
                source=source,
                summary=summary,
                score=score,
                reasons=reasons,
            )
        )

    items.sort(key=lambda x: (x.published, x.score), reverse=True)
    return items[:MAX_ITEMS]


def write_rss(items: list[FeedItem]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fg = FeedGenerator()
    fg.id(FEED_URL)
    fg.title(FEED_TITLE)
    fg.link(href=FEED_URL, rel="self")
    fg.link(href=FEED_URL.rsplit("/", 1)[0] + "/", rel="alternate")
    fg.description(FEED_DESCRIPTION)
    fg.language("en")
    fg.lastBuildDate(datetime.now(timezone.utc))

    for item in items:
        entry = fg.add_entry()
        entry.id(item.guid)
        entry.title(item.title)
        entry.link(href=item.link)
        entry.description(item.summary)
        entry.author({"name": item.authors})
        entry.published(datetime.combine(item.published, datetime.min.time(), tzinfo=timezone.utc))
        entry.updated(datetime.now(timezone.utc))

    fg.rss_file(str(OUTPUT_PATH), pretty=True)


def write_index(items: list[FeedItem]) -> None:
    """Optional human-readable page for GitHub Pages."""
    index_path = OUTPUT_PATH.parent / "index.html"
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    rows = []
    for item in items[:50]:
        rows.append(
            "<li>"
            f"<a href='{html.escape(item.link)}'>{html.escape(item.title)}</a><br>"
            f"<small>{item.published.isoformat()} | {html.escape(item.source)} | "
            f"Score: {item.score}</small>"
            "</li>"
        )

    index_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(FEED_TITLE)}</title>
</head>
<body>
  <h1>{html.escape(FEED_TITLE)}</h1>
  <p>{html.escape(FEED_DESCRIPTION)}</p>
  <p><a href="feed.xml">RSS feed</a></p>
  <p><small>Generated {generated}</small></p>
  <ol>
    {''.join(rows)}
  </ol>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    works = fetch_openalex_works()
    items = make_feed_items(works)
    write_rss(items)
    write_index(items)
    print(f"Wrote {len(items)} items to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
