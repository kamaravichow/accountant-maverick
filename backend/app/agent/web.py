"""TinyFish Search + Fetch clients (live web research for the agent).

API contract (from the official `tinyfish` SDK):
  Search: GET  https://api.search.tinyfish.ai/?query=...   header X-API-Key
          optional: location, language, include_domains, exclude_domains, after_date, before_date,
                    recency_minutes, domain_type, page
          -> {query, results: [{position, site_name, title, snippet, url, date?, ...}], total_results, page}
  Fetch:  POST https://api.fetch.tinyfish.ai/  {"urls": [...<=10], "format": "markdown", ...}
          -> {results: [{url, final_url, title, description, published_date, text, links, ...}],
              errors: [{url, error}]}
"""

from __future__ import annotations

import httpx

from ..config import get_settings

# Authoritative Indian sources the agent should prefer for law/rates/due dates.
TRUSTED_DOMAINS = [
    "incometaxindia.gov.in", "incometax.gov.in", "cbic-gst.gov.in", "cbic.gov.in", "gst.gov.in", "tutorial.gst.gov.in",
    "gstcouncil.gov.in", "egazette.gov.in", "indiabudget.gov.in", "mca.gov.in", "rbi.org.in", "epfindia.gov.in",
    "esic.gov.in", "udyamregistration.gov.in", "tdscpc.gov.in", "protean-tinpan.com", "icai.org", "pib.gov.in",
    "taxmann.com", "taxguru.in", "caclubindia.com", "cleartax.in",
]


class TinyFishError(RuntimeError):
    pass


def _headers() -> dict:
    key = get_settings().tinyfish_api_key
    if not key:
        raise TinyFishError("TINYFISH_API_KEY is not configured - live web search is unavailable. "
                            "Answer from the preset rate tables and tell the user the rate could not be verified live.")
    return {"X-API-Key": key, "Accept": "application/json", "Content-Type": "application/json",
            "User-Agent": "accountant-maverick/1.0"}


def _raise(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        raise TinyFishError("TinyFish rate limit reached (free tier ~5 requests/minute). Wait and retry, or "
                            "reduce the number of searches.")
    if resp.status_code >= 400:
        raise TinyFishError(f"TinyFish HTTP {resp.status_code}: {resp.text[:300]}")


async def search(query: str, *, include_domains: list[str] | None = None, exclude_domains: list[str] | None = None,
                 location: str | None = None, language: str | None = None, recency_minutes: int | None = None,
                 after_date: str | None = None, page: int | None = None) -> dict:
    s = get_settings()
    params: dict[str, str] = {"query": query}
    if include_domains:
        params["include_domains"] = ",".join(include_domains)
    if exclude_domains:
        params["exclude_domains"] = ",".join(exclude_domains)
    if location:
        params["location"] = location
    if language:
        params["language"] = language
    if recency_minutes:
        params["recency_minutes"] = str(recency_minutes)
    if after_date:
        params["after_date"] = after_date
    if page is not None:
        params["page"] = str(page)
    async with httpx.AsyncClient(timeout=s.tinyfish_timeout_seconds) as client:
        resp = await client.get(s.tinyfish_search_url, params=params, headers=_headers())
    _raise(resp)
    return resp.json()


async def fetch(urls: list[str], *, fmt: str = "markdown", highlights_query: str | None = None,
                max_snippets: int = 8) -> dict:
    s = get_settings()
    if not urls:
        raise TinyFishError("No URLs given")
    body: dict = {"urls": urls[:10], "format": fmt, "links": False, "image_links": False}
    if highlights_query and fmt == "markdown":
        body["highlights"] = {"query": highlights_query, "max_snippets": max_snippets, "include_full_page_text": True}
    async with httpx.AsyncClient(timeout=s.tinyfish_timeout_seconds * 2) as client:
        resp = await client.post(s.tinyfish_fetch_url, json=body, headers=_headers())
    _raise(resp)
    return resp.json()
