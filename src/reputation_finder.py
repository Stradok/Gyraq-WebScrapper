import logging
import random
import re
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

log = logging.getLogger(__name__)

# DuckDuckGo's HTML endpoint, not google.com/search - Google blocks headless
# automation on the first request (redirects to /sorry/index, verified live),
# while DDG's index still surfaces the same LinkedIn/review/forum pages.
SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"


COMPLAINT_SITES = (
    "trustpilot.com", "yelp.com", "bbb.org", "ripoffreport.com", "pissedconsumer.com",
    "complaintsboard.com", "sitejabber.com", "consumeraffairs.com",
)

NEGATIVE_RE = re.compile(
    r"scam|rip.?off|complain|worst|terrible|awful|horrible|avoid|never again|overcharg|unprofessional|"
    r"poor service|bad service|disappoint|refund|no show|didn'?t show|ghosted|unresponsive|not recommend|"
    r"fraud|lawsuit|warning|nightmare",
    re.I,
)


def mentions_from(reputation: dict) -> list[dict]:
    """Flatten the research into a list of {source, title, url, snippet, negative}."""
    out = []
    for key, label in (("reddit", "Reddit"), ("quora", "Quora"), ("complaints", "Complaint sites"), ("reviews", "Review sites")):
        for r in reputation.get(key, []) or []:
            text = f"{r.get('title', '')} {r.get('snippet', '')}"
            out.append(
                {
                    "source": label,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                    "negative": bool(NEGATIVE_RE.search(text)),
                }
            )
    return out


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

        _jitter(1.0, 2.0)

        quora_raw = _search_snippets(page, f'"{business_name}" {loc} quora')
        quora = [r for r in quora_raw if "quora.com" in r["url"]][:3]

        _jitter(1.0, 2.0)

        complaint_raw = _search_snippets(
            page, f'"{business_name}" {loc} complaints trustpilot OR yelp OR bbb OR "ripoff report"'
        )
        complaints = [
            r for r in complaint_raw if any(d in r["url"] for d in COMPLAINT_SITES)
        ][:3]

        _jitter(1.0, 2.0)

        linkedin_raw = _search_snippets(page, f'"{business_name}" {loc} linkedin')
        linkedin = [r for r in linkedin_raw if "linkedin.com" in r["url"]][:2]

        _jitter(1.0, 2.0)

        social_raw = _search_snippets(page, f'"{business_name}" {loc} instagram OR facebook')
        social = [
            r for r in social_raw if "instagram.com" in r["url"] or "facebook.com" in r["url"]
        ][:2]

        return {
            "reddit": reddit,
            "quora": quora,
            "complaints": complaints,
            "reviews": reviews,
            "linkedin": linkedin,
            "social": social,
        }
    except Exception:
        log.warning("Reputation research failed for %r", business_name, exc_info=True)
        return {}
    finally:
        try:
            page.close()
        except Exception:
            pass
