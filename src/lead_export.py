"""Export scraped businesses as a cold-call list: contact details, why each
business is losing customers, how to fix it, and a call script. Everything
is derived from the scraped data itself (rule-based, no LLM), and the
competitor comparison only uses businesses from the same search."""
import csv
import io
import json
import re
import statistics
from datetime import datetime, timezone

from .company_profile import get_company_profile
from .results_store import read_result_file

KINDS = ("phones", "emails", "both")
FORMATS = ("csv", "json")
LOW_RATING = 4.0

EXPORT_FIELDS = [
    "name", "category", "phone", "email", "website", "address", "rating",
    "review_count", "search_query", "issues", "how_we_can_help",
    "competitor_benchmark", "call_script",
]


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _benchmark(biz: dict, peers: list[dict]) -> tuple[dict | None, float | None]:
    """(strongest competitor by reviews in the same search, peer median reviews)."""
    others = [p for p in peers if p is not biz and p.get("review_count")]
    if not others:
        return None, None
    top = max(others, key=lambda p: p["review_count"])
    return top, statistics.median(p["review_count"] for p in others)


def analyze(biz: dict, peers: list[dict]) -> list[tuple[str, str]]:
    """Return [(issue, fix)] in priority order."""
    gaps = []
    top, median = _benchmark(biz, peers)
    reviews = biz.get("review_count") or 0
    rating = biz.get("rating")

    if not biz.get("website"):
        gaps.append((
            "No website - customers who find them on Google Maps have nowhere to learn more, book or enquire",
            "Build a fast mobile-friendly site with click-to-call and an enquiry/booking form",
        ))
    elif not biz.get("email"):
        gaps.append((
            "No public contact email on their site - every enquiry has to be a phone call during opening hours",
            "Add a contact form and automatic email/WhatsApp follow-up so no enquiry is missed",
        ))
    if rating is not None and rating < LOW_RATING:
        gaps.append((
            f"Rated {rating} - below the 4.0 many customers filter out",
            "Set up automated review requests to happy customers and reply to negative reviews",
        ))
    if median is not None and reviews < median:
        gaps.append((
            f"Only {reviews} reviews vs a typical {int(median)} for competitors in the same search",
            "Run a review-collection system (QR code + SMS/WhatsApp request after each job)",
        ))
    elif median is None and reviews < 20:
        gaps.append((
            f"Only {reviews} reviews - little social proof",
            "Run a review-collection system (QR code + SMS/WhatsApp request after each job)",
        ))
    if not biz.get("hours"):
        gaps.append((
            "No opening hours on their Google listing - customers can't tell if they're open",
            "Complete and optimise their Google Business Profile",
        ))
    return gaps


def _competitor_line(biz: dict, peers: list[dict]) -> str:
    top, _ = _benchmark(biz, peers)
    # Only a stronger competitor is a useful comparison.
    if not top or (top.get("review_count") or 0) <= (biz.get("review_count") or 0):
        return ""
    bits = [f"{top.get('name')}: {top['review_count']} reviews"]
    if top.get("rating"):
        bits.append(f"{top['rating']} stars")
    bits.append("has a website" if top.get("website") else "no website")
    return ", ".join(bits)


def call_script(biz: dict, gaps: list[tuple[str, str]], peers: list[dict], company: dict) -> str:
    us = company.get("company_name") or "our team"
    name = biz.get("name") or "your business"
    category = (biz.get("category") or "business").lower()
    top, _ = _benchmark(biz, peers)
    if top and (top.get("review_count") or 0) <= (biz.get("review_count") or 0):
        top = None
    rival = top.get("name") if top else f"other {category}s nearby"

    if not gaps:
        return (
            f"Hi, is this {name}? I'm calling from {us}. You're doing well online compared to other "
            f"{category}s nearby, so I'll keep it short - we help strong businesses turn that visibility "
            "into more booked jobs. Could I send you a two-minute overview? "
            "What's the best email or WhatsApp number for you?"
        )

    lines = [
        f"Hi, is this {name}? Quick one - I'm calling from {us}. I'll be brief: "
        f"I was looking at {category}s in your area on Google and noticed something that's costing you customers.",
    ]
    if gaps:
        lines.append(f"Right now: {gaps[0][0].split(' - ')[0].lower()}.")
    if top:
        lines.append(
            f"Meanwhile {rival} is showing up with {top['review_count']} reviews"
            f"{' and a proper website' if top.get('website') else ''}. "
            "When someone searches, they're the ones getting the call - you're losing that money "
            "while they take it."
        )
    else:
        lines.append(
            "Every day, people searching for a {0} nearby are choosing whoever looks most "
            "established online - and right now that isn't you.".format(category)
        )
    if gaps:
        lines.append(f"The good news is it's fixable: {gaps[0][1].lower()}.")
    lines.append(
        "Could I send you a short breakdown of exactly where you stand against your competitors? "
        "It takes two minutes to look at - what's the best email or WhatsApp number for you?"
    )
    return "\n".join(lines)


def _collect(files: list[str], kind: str) -> list[dict]:
    company = get_company_profile()
    rows, seen = [], set()
    for file in files:
        data = read_result_file(file)
        if not data:
            continue
        peers = data.get("results") or []
        for biz in peers:
            phone, email = biz.get("phone"), (biz.get("email") or "").strip()
            if kind == "phones" and not phone:
                continue
            if kind == "emails" and not email:
                continue
            if kind == "both" and not (phone or email):
                continue
            key = _digits(phone) or email.lower()
            if key in seen:
                continue
            seen.add(key)
            gaps = analyze(biz, peers)
            rows.append({
                "name": biz.get("name"),
                "category": biz.get("category"),
                "phone": phone if kind != "emails" else None,
                "email": email or None if kind != "phones" else None,
                "website": biz.get("website"),
                "address": biz.get("address"),
                "rating": biz.get("rating"),
                "review_count": biz.get("review_count"),
                "search_query": data.get("query"),
                "issues": " | ".join(i for i, _ in gaps),
                "how_we_can_help": " | ".join(f for _, f in gaps),
                "competitor_benchmark": _competitor_line(biz, peers),
                "call_script": call_script(biz, gaps, peers, company),
            })
    return rows


def build_export(files: list[str], kind: str, fmt: str) -> tuple[bytes, str, str]:
    rows = _collect(files, kind)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"leads_{kind}_{stamp}.{fmt}"
    if fmt == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2).encode(), name, "application/json"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    # BOM so Excel opens UTF-8 correctly.
    return ("﻿" + buf.getvalue()).encode("utf-8"), name, "text/csv"
