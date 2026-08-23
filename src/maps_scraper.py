import logging
import random
import re
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from playwright_stealth import Stealth

from . import config
from .drafts_store import save_draft
from .email_finder import find_email
from .live_view import set_frame
from .models import Business, Review
from .pitch_writer import generate_pitch
from .reputation_finder import find_reputation_signals
from .seen_store import SeenStore, extract_place_id

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

COORD_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")
COORD_FALLBACK_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
REVIEW_COUNT_RE = re.compile(r"\(([\d,]+)\)")
PRICE_RE = re.compile(r"\${1,4}")
STARS_RE = re.compile(r"([\d.]+)\s*star")


def _jitter(a: float, b: float) -> None:
    time.sleep(random.uniform(a, b))


def _safe_text(page: Page, selector: str) -> str | None:
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return None
        text = loc.inner_text(timeout=2000).strip()
        return text or None
    except Exception:
        return None


def _safe_attr(page: Page, selector: str, attr: str) -> str | None:
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return None
        val = loc.get_attribute(attr, timeout=2000)
        return val.strip() if val else None
    except Exception:
        return None


class MapsScraper:
    def __init__(self, headless: bool = True, seen_store: SeenStore | None = None):
        self.headless = headless
        self.seen_store = seen_store
        self._playwright = None
        self.browser = None
        self.context = None
        self.page: Page | None = None

    def start(self) -> None:
        self._playwright = Stealth().use_sync(sync_playwright()).start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = self.browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        self.page = self.context.new_page()
        self.page.set_default_navigation_timeout(config.NAV_TIMEOUT_MS)
        self.page.set_default_timeout(config.NAV_TIMEOUT_MS)

    def stop(self) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            log.warning("Error during scraper shutdown", exc_info=True)

    def _accept_cookies(self) -> None:
        for selector in (
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'form:nth-of-type(2) button',
        ):
            try:
                btn = self.page.locator(selector).first
                if btn.count() and btn.is_visible(timeout=1000):
                    btn.click(timeout=1500)
                    _jitter(0.5, 1.2)
                    return
            except Exception:
                continue

    def _snapshot(self) -> None:
        try:
            data = self.page.screenshot(type="jpeg", quality=50, timeout=3000)
            set_frame(data)
        except Exception:
            pass

    def search(self, query: str, max_results: int) -> list[Business]:
        page = self.page
        url = f"https://www.google.com/maps/search/{quote(query)}?hl=en"
        log.info("Navigating to search: %s", url)
        page.goto(url, wait_until="domcontentloaded")
        _jitter(1.5, 3.0)
        self._accept_cookies()

        try:
            page.wait_for_selector('div[role="feed"], h1', timeout=15000)
        except PWTimeout:
            log.warning("Timed out waiting for results for query %r", query)
            return []

        self._snapshot()

        if page.locator('div[role="feed"]').count() == 0:
            # Query resolved directly to a single business detail page.
            if self.seen_store is not None and self.seen_store.has(extract_place_id(page.url)):
                log.info("Skipping already-seen business for %r", query)
                return []
            biz = self._extract_current_business()
            if biz:
                self._mark_seen(biz)
            return [biz] if biz else []

        listings = self._collect_listing_links(max_results)
        log.info("Collected %d new listing link(s) for %r", len(listings), query)

        businesses: list[Business] = []
        for i, (name_hint, href) in enumerate(listings[:max_results]):
            log.info("[%d/%d] %s", i + 1, min(len(listings), max_results), name_hint or href)
            try:
                page.goto(href, wait_until="domcontentloaded")
                page.wait_for_selector("h1", timeout=15000)
                _jitter(1.0, 2.5)
                self._snapshot()
                biz = self._extract_current_business()
                if biz:
                    self._mark_seen(biz)
                    businesses.append(biz)
            except Exception:
                log.warning("Failed to extract listing %r", name_hint or href, exc_info=True)
            _jitter(0.8, 2.0)

        return businesses

    def _mark_seen(self, biz: Business) -> None:
        biz.place_id = extract_place_id(biz.google_maps_url)
        if self.seen_store is not None:
            self.seen_store.add(biz.place_id)

    def _collect_listing_links(self, max_results: int) -> list[tuple[str | None, str]]:
        page = self.page
        feed = page.locator('div[role="feed"]').first
        seen: dict[str, str | None] = {}
        stable_rounds = 0

        def _new_count() -> int:
            if self.seen_store is None:
                return len(seen)
            return sum(1 for href in seen if not self.seen_store.has(extract_place_id(href)))

        while _new_count() < max_results and stable_rounds < 4:
            links = page.locator('div[role="feed"] a.hfpxzc')
            count = links.count()
            for i in range(count):
                try:
                    href = links.nth(i).get_attribute("href")
                    name = links.nth(i).get_attribute("aria-label")
                except Exception:
                    continue
                if href and href not in seen:
                    seen[href] = name

            end_reached = page.locator("text=You've reached the end of the list").count() > 0
            if end_reached:
                break

            before = len(seen)
            try:
                feed.evaluate("el => el.scrollTop = el.scrollHeight")
            except Exception:
                break
            self._snapshot()
            _jitter(1.0, 2.0)
            if len(seen) == before:
                stable_rounds += 1
            else:
                stable_rounds = 0

        results = [(name, href) for href, name in seen.items()]
        if self.seen_store is not None:
            results = [
                (name, href) for name, href in results
                if not self.seen_store.has(extract_place_id(href))
            ]
        return results

    def _extract_current_business(self) -> Business | None:
        page = self.page
        name = _safe_text(page, "h1")
        if not name:
            return None

        biz = Business(name=name)
        biz.google_maps_url = page.url

        m = COORD_RE.search(page.url) or COORD_FALLBACK_RE.search(page.url)
        if m:
            biz.latitude, biz.longitude = float(m.group(1)), float(m.group(2))

        biz.category = _safe_text(page, "button.DkEaL")

        rating_text = _safe_text(page, 'div.F7nice span[aria-hidden="true"]')
        if rating_text:
            try:
                biz.rating = float(rating_text.replace(",", "."))
            except ValueError:
                pass

        review_block = _safe_text(page, "div.F7nice")
        if review_block:
            m = REVIEW_COUNT_RE.search(review_block)
            if m:
                try:
                    biz.review_count = int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
            pm = PRICE_RE.search(review_block)
            if pm:
                biz.price_level = pm.group(0)

        if not biz.price_level:
            top_row = _safe_text(page, "div.LBgpqf") or _safe_text(page, "div.skqShb")
            if top_row:
                pm = PRICE_RE.search(top_row)
                if pm:
                    biz.price_level = pm.group(0)

        addr = _safe_attr(page, 'button[data-item-id="address"]', "aria-label")
        biz.address = addr.split(":", 1)[-1].strip() if addr else None

        phone = _safe_attr(page, 'button[data-item-id^="phone"]', "aria-label")
        biz.phone = phone.split(":", 1)[-1].strip() if phone else None

        website_href = _safe_attr(page, 'a[data-item-id="authority"]', "href")
        biz.website = website_href

        if config.SCRAPE_EMAILS and biz.website:
            biz.email = find_email(self.context, biz.website, config.EMAIL_FETCH_TIMEOUT_MS)

        biz.hours = self._extract_hours()

        biz.reviews = self._extract_reviews(config.REVIEWS_PER_BUSINESS)

        if config.GENERATE_PITCHES and biz.email:
            reputation = {}
            if config.RESEARCH_REPUTATION:
                reputation = find_reputation_signals(
                    self.context, biz.name, biz.address, config.REPUTATION_TIMEOUT_MS
                )
            pitch = generate_pitch(biz, reputation)
            if pitch:
                save_draft(biz.email, pitch["subject"], pitch["body"], biz.name, pitch["pitch"])
                log.info("Drafted %r pitch for %r -> %s", pitch["pitch"], biz.name, biz.email)

        return biz

    def _extract_hours(self) -> str | None:
        page = self.page
        try:
            toggle = page.locator('div.OMl5r[role="button"]').first
            toggle.scroll_into_view_if_needed(timeout=3000)
            toggle.click(timeout=3000)
            page.wait_for_selector("table.eK4R0e tr", timeout=4000)
        except Exception:
            return None

        rows = page.locator("table.eK4R0e tr")
        lines = []
        for i in range(rows.count()):
            row = rows.nth(i)
            day = _safe_text_in(row, "td.ylH6lf")
            hours = _safe_attr_in(row, "td.mxowUb", "aria-label")
            if day and hours:
                lines.append(f"{day}: {hours}")
        return "; ".join(lines) if lines else None

    def _extract_reviews(self, limit: int) -> list[Review]:
        if limit <= 0:
            return []
        page = self.page
        reviews: list[Review] = []
        try:
            tab = page.get_by_role("tab", name=re.compile("Reviews", re.I)).first
            tab.wait_for(state="visible", timeout=6000)
            tab.click(timeout=3000)
            _jitter(1.0, 2.0)
            page.wait_for_selector("div[data-review-id]", timeout=8000)
        except Exception:
            return []

        items = page.locator("div[data-review-id]")
        seen_ids: set[str] = set()
        for i in range(items.count()):
            if len(reviews) >= limit:
                break
            item = items.nth(i)
            try:
                review_id = item.get_attribute("data-review-id", timeout=1500)
            except Exception:
                review_id = None
            if review_id:
                if review_id in seen_ids:
                    continue
                seen_ids.add(review_id)
            try:
                author = _safe_text_in(item, "div.d4r55")
                stars_label = _safe_attr_in(item, "span[role='img']", "aria-label")
                rating = None
                if stars_label:
                    m = STARS_RE.search(stars_label)
                    if m:
                        rating = float(m.group(1))
                relative_time = _safe_text_in(item, "span.rsqaWe")
                text = _safe_text_in(item, "span.wiI7pd")
                reviews.append(
                    Review(author=author, rating=rating, relative_time=relative_time, text=text)
                )
            except Exception:
                continue
        return reviews


def _safe_text_in(locator, selector: str) -> str | None:
    try:
        sub = locator.locator(selector).first
        if sub.count() == 0:
            return None
        text = sub.inner_text(timeout=1500).strip()
        return text or None
    except Exception:
        return None


def _safe_attr_in(locator, selector: str, attr: str) -> str | None:
    try:
        sub = locator.locator(selector).first
        if sub.count() == 0:
            return None
        val = sub.get_attribute(attr, timeout=1500)
        return val.strip() if val else None
    except Exception:
        return None
