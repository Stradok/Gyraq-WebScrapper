import logging
import random
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

log = logging.getLogger(__name__)

SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"


def _jitter(a: float, b: float) -> None:
    time.sleep(random.uniform(a, b))


def _clean_ddg_url(href: str) -> str:
    """DuckDuckGo's HTML results wrap the real URL in a redirect link
    (//duckduckgo.com/l/?uddg=<encoded-real-url>&...) - unwrap it."""
    if not href:
        return href
    try:
        parsed = urlparse(href if href.startswith("http") else "https:" + href)
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            return unquote(qs["uddg"][0])
    except Exception:
        pass
    return href


def _search_snippets(page, query: str, limit: int = 5) -> list[dict]:
    url = SEARCH_URL.format(q=quote(query))
    try:
        page.goto(url, wait_until="domcontentloaded")
    except Exception:
        return []

    results: list[dict] = []
    try:
        items = page.locator("div.result")
        count = min(items.count(), limit * 3)
        for i in range(count):
            item = items.nth(i)
            try:
                link_el = item.locator("a.result__a").first
                title = link_el.inner_text(timeout=1000).strip()
                url_ = _clean_ddg_url(link_el.get_attribute("href", timeout=1000) or "")
                snippet = item.locator(".result__snippet").first.inner_text(timeout=1000).strip()
            except Exception:
                continue
            if title or snippet:
                results.append({"title": title, "url": url_, "snippet": snippet})
            if len(results) >= limit:
                break
    except Exception:
        pass
    return results


def find_reputation_signals(
    context, business_name: str | None, location_hint: str | None, timeout_ms: int = 15000
) -> dict:
    """Best-effort search for real Reddit threads / review-site mentions of a
    business, to ground outreach copy in actual evidence rather than
    generic claims. Returns {} on any failure - never blocks scraping."""
    if not business_name:
        return {}

    page = context.new_page()
    page.set_default_navigation_timeout(timeout_ms)
    page.set_default_timeout(timeout_ms)
    try:
        loc = (location_hint or "").split(",")[0].strip()

        reddit_raw = _search_snippets(page, f'"{business_name}" {loc} reddit')
        reddit = [r for r in reddit_raw if "reddit.com" in r["url"]][:3]

        _jitter(1.0, 2.0)

        review_raw = _search_snippets(page, f'"{business_name}" {loc} reviews complaints')
        reviews = [
            r
            for r in review_raw
            if "reddit.com" not in r["url"] and "google.com/maps" not in r["url"]
        ][:3]

        return {"reddit": reddit, "reviews": reviews}
    except Exception:
        log.warning("Reputation research failed for %r", business_name, exc_info=True)
        return {}
    finally:
        try:
            page.close()
        except Exception:
            pass
