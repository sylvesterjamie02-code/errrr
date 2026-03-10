#!/usr/bin/env python3
"""Scrape badminton session availability for Mile End and Whitechapel venues."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


@dataclass(frozen=True)
class Venue:
    name: str
    slug: str
    url: str


VENUES: tuple[Venue, ...] = (
    Venue(
        name="Mile End Park Leisure Centre",
        slug="mile-end",
        url="https://bookings.better.org.uk/location/mile-end-park-leisure-centre/badminton",
    ),
    Venue(
        name="Whitechapel Sports Centre",
        slug="whitechapel",
        url="https://bookings.better.org.uk/location/whitechapel-sports-centre/badminton",
    ),
)

SLOT_SELECTORS: tuple[str, ...] = (
    '[data-testid*="session"]',
    '[data-testid*="slot"]',
    '.bookable-event',
    '.session-card',
    '.timeslot',
    'li',
)

TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")
DATE_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}\s+[A-Za-z]{3,9})\b",
    flags=re.IGNORECASE,
)
AVAILABILITY_RE = re.compile(
    r"(?P<count>\d+)\s*(?:spaces?|courts?)\s*(?:left|available)?",
    flags=re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days ahead to include in report (default: 7).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory where JSON/CSV reports are written.",
    )
    return parser.parse_args()


async def dismiss_cookie_banner(page: Page) -> None:
    cookie_selectors = (
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        '#onetrust-accept-btn-handler',
        '[aria-label="Accept cookies"]',
    )
    for selector in cookie_selectors:
        button = page.locator(selector).first
        if await button.count() > 0:
            try:
                await button.click(timeout=1500)
                return
            except Exception:
                continue


async def extract_venue_rows(page: Page, venue: Venue, days: int) -> list[dict[str, Any]]:
    await page.goto(venue.url, wait_until="domcontentloaded", timeout=90_000)
    await dismiss_cookie_banner(page)
    await page.wait_for_timeout(3_000)

    row_candidates: list[str] = []
    for selector in SLOT_SELECTORS:
        locator = page.locator(selector)
        count = await locator.count()
        if count == 0:
            continue
        for i in range(min(count, 600)):
            txt = (await locator.nth(i).inner_text()).strip()
            if txt:
                row_candidates.append(" ".join(txt.split()))

    unique_rows = list(dict.fromkeys(row_candidates))
    today = date.today()
    cutoff = today + timedelta(days=days)

    parsed_rows: list[dict[str, Any]] = []
    for raw in unique_rows:
        if "badminton" not in raw.lower() and "court" not in raw.lower():
            continue

        time_match = TIME_RE.search(raw)
        if not time_match:
            continue

        date_match = DATE_RE.search(raw)
        availability_match = AVAILABILITY_RE.search(raw)
        available_count = int(availability_match.group("count")) if availability_match else None

        parsed_date: str | None = None
        if date_match:
            parsed_date = normalize_date(date_match.group(0), today)

        if parsed_date is not None:
            slot_day = datetime.strptime(parsed_date, "%Y-%m-%d").date()
            if slot_day < today or slot_day > cutoff:
                continue

        parsed_rows.append(
            {
                "venue": venue.name,
                "venue_slug": venue.slug,
                "date": parsed_date,
                "time": time_match.group(0),
                "available_courts_or_spaces": available_count,
                "raw_text": raw,
                "source_url": venue.url,
            }
        )

    if not parsed_rows:
        parsed_rows.append(
            {
                "venue": venue.name,
                "venue_slug": venue.slug,
                "date": None,
                "time": None,
                "available_courts_or_spaces": None,
                "raw_text": "No badminton slot rows matched configured selectors/regex.",
                "source_url": venue.url,
            }
        )

    return parsed_rows


def normalize_date(raw: str, today: date) -> str | None:
    clean = " ".join(raw.replace(",", " ").split())
    known_formats = (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d %b",
        "%d %B",
    )
    clean = re.sub(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+", "", clean, flags=re.IGNORECASE)
    for fmt in known_formats:
        try:
            parsed = datetime.strptime(clean, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


async def scrape(days: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=True)
        context: BrowserContext = await browser.new_context()
        page: Page = await context.new_page()
        for venue in VENUES:
            try:
                rows.extend(await extract_venue_rows(page, venue, days))
            except Exception as exc:
                rows.append(
                    {
                        "venue": venue.name,
                        "venue_slug": venue.slug,
                        "date": None,
                        "time": None,
                        "available_courts_or_spaces": None,
                        "raw_text": f"Scrape failed: {exc}",
                        "source_url": venue.url,
                    }
                )
        await context.close()
        await browser.close()
    return rows


def write_json(rows: list[dict[str, Any]], output_file: Path) -> None:
    output_file.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def write_csv(rows: list[dict[str, Any]], output_file: Path) -> None:
    fieldnames = [
        "venue",
        "venue_slug",
        "date",
        "time",
        "available_courts_or_spaces",
        "raw_text",
        "source_url",
    ]
    with output_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = asyncio.run(scrape(days=args.days))

    write_json(rows, args.output_dir / "availability.json")
    write_csv(rows, args.output_dir / "availability.csv")

    print(f"Wrote {len(rows)} row(s) to {args.output_dir}/availability.json and availability.csv")


if __name__ == "__main__":
    main()
