#!/usr/bin/env python3
"""Build README.md (current year) and archive/<year>.md (past years) from data/<year>.yaml.

Usage:
  python scripts/generate.py                     validate, then write the markdown files
  python scripts/generate.py --validate          validate only (what pull requests run)
  python scripts/generate.py --today 2026-12-02  pretend it's another day (to preview expiry)

The newest data/<year>.yaml becomes README.md. Every older year becomes archive/<year>.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TEMPLATE_DIR = ROOT / "templates"
README = ROOT / "README.md"
ARCHIVE_DIR = ROOT / "archive"

# Deals are treated as expired once this time zone's calendar passes their end date.
# Pacific is the safe choice: most vendors end sales at midnight PT or earlier.
TIMEZONE = ZoneInfo("America/Los_Angeles")

TOP_KEYS = {"meta", "sections"}
META_KEYS = {"year", "title", "intro", "credits"}
SECTION_KEYS = {"id", "title", "emoji", "deals"}
DEAL_KEYS = {"vendor", "url", "deal", "code", "starts", "ends", "ends_note",
             "focus", "notes", "taken", "used"}
REQUIRED_DEAL_KEYS = ("vendor", "url", "deal")

# Query parameters that mean a link is carrying affiliate or tracking info.
TRACKING_PARAMS = {"ref", "referral", "referrer", "aff", "affid", "aff_id", "affiliate",
                   "affiliate_id", "via", "tag", "partner", "irclickid", "clickid",
                   "gclid", "fbclid", "mc_cid", "mc_eid"}
BLOCKED_HOSTS = ("amazon.", "amzn.")

UPDATED_LINE = re.compile(r"^_Last updated: .*_$", re.MULTILINE)


class DataLoader(yaml.SafeLoader):
    """SafeLoader that leaves dates as text, so a bad date gets a friendly error instead of a crash."""


DataLoader.yaml_implicit_resolvers = {
    first_char: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


# --------------------------------------------------------------------------- validation

class Problems:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []  # (file, where, message)

    def add(self, file: str, where: str, message: str) -> None:
        self.items.append((file, where, message))

    def __bool__(self) -> bool:
        return bool(self.items)

    def report(self) -> None:
        in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        for file, where, message in self.items:
            if in_actions:  # shows up as an annotation on the PR
                print(f"::error file={file},title=Deal list problem::{where}: {message}")
            else:
                print(f"{file}: {where}: {message}", file=sys.stderr)
        print(f"\n{len(self.items)} problem(s) found.", file=sys.stderr)


def to_date(value):
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip())
    raise ValueError(value)


def text_or_empty(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def check_url(url: str, file: str, where: str, problems: Problems) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        problems.add(file, where, f"url must be a full link starting with https:// (got {url!r})")
        return False
    host = (parsed.hostname or "").lower()
    if any(blocked in host for blocked in BLOCKED_HOSTS):
        problems.add(file, where, "Amazon links aren't accepted on this list")
        return False
    tracking = sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
                       if key.lower() in TRACKING_PARAMS or key.lower().startswith("utm_")})
    if tracking:
        problems.add(file, where, f"url has tracking/affiliate parameters ({', '.join(tracking)}); "
                                  "please link to the plain page")
        return False
    return True


def validate_deal(deal, file: str, where: str, problems: Problems):
    if not isinstance(deal, dict):
        problems.add(file, where, "each deal must be a mapping (vendor:, url:, deal:, ...)")
        return None
    if isinstance(deal.get("vendor"), str):
        where = f"{where} ({deal['vendor'].strip()})"
    count_before = len(problems.items)

    for key in sorted(set(deal) - DEAL_KEYS):
        problems.add(file, where, f"unknown field '{key}' (allowed: {', '.join(sorted(DEAL_KEYS))})")

    for key in REQUIRED_DEAL_KEYS:
        if not isinstance(deal.get(key), str) or not deal[key].strip():
            problems.add(file, where, f"'{key}' is required and must be text")

    if isinstance(deal.get("url"), str):
        check_url(deal["url"].strip(), file, where, problems)

    raw_codes = deal.get("code")
    raw_codes = [] if raw_codes is None else raw_codes if isinstance(raw_codes, list) else [raw_codes]
    codes = []
    for code in raw_codes:
        if isinstance(code, str) and code.strip():
            codes.append(code.strip())
        else:
            # YAML turns NO/YES/ON into booleans and 0042 into 42, so codes must be quoted.
            problems.add(file, where, f"a code isn't text (YAML read it as {code!r}); put it in quotes, e.g. code: \"BF26\"")

    dates = {}
    for key in ("starts", "ends"):
        try:
            dates[key] = to_date(deal.get(key))
        except (ValueError, TypeError):
            problems.add(file, where, f"'{key}' must be a date written like 2026-12-01")
            dates[key] = None
    if dates["starts"] and dates["ends"] and dates["starts"] > dates["ends"]:
        problems.add(file, where, "'starts' is after 'ends'")

    for key in ("ends_note", "focus", "notes"):
        if deal.get(key) is not None and not isinstance(deal[key], str):
            problems.add(file, where, f"'{key}' must be text")
    for key in ("taken", "used"):
        if key in deal and not isinstance(deal[key], bool):
            problems.add(file, where, f"'{key}' must be true or false")

    if len(problems.items) > count_before:
        return None
    return {
        "vendor": deal["vendor"].strip(),
        "url": deal["url"].strip(),
        "deal": deal["deal"].strip(),
        "codes": codes,
        "starts": dates["starts"],
        "ends": dates["ends"],
        "ends_note": text_or_empty(deal.get("ends_note")),
        "focus": text_or_empty(deal.get("focus")),
        "notes": text_or_empty(deal.get("notes")),
        "taken": deal.get("taken") is True,
        "used": deal.get("used") is True,
    }


def validate_file(path: Path, data, problems: Problems):
    file = str(path.relative_to(ROOT))
    if not isinstance(data, dict):
        problems.add(file, "top level", "must be a mapping with 'meta' and 'sections'")
        return None
    for key in sorted(set(data) - TOP_KEYS):
        problems.add(file, "top level", f"unknown key '{key}'")

    meta = data.get("meta") or {}
    if not isinstance(meta, dict):
        problems.add(file, "meta", "must be a mapping")
        meta = {}
    for key in sorted(set(meta) - META_KEYS):
        problems.add(file, "meta", f"unknown key '{key}'")
    year = int(path.stem)
    if meta.get("year") != year:
        problems.add(file, "meta.year", f"should be {year} to match the file name")
    if not isinstance(meta.get("title"), str):
        problems.add(file, "meta.title", "is required")
    credits = meta.get("credits") or []
    if not isinstance(credits, list) or not all(isinstance(c, str) for c in credits):
        problems.add(file, "meta.credits", "must be a list of names (text)")
        credits = []

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        problems.add(file, "sections", "must be a non-empty list")
        return None

    out_sections, seen_ids = [], set()
    for i, section in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(section, dict):
            problems.add(file, where, "must be a mapping with id, title and deals")
            continue
        sid = section.get("id")
        if not isinstance(sid, str) or not sid:
            problems.add(file, where, "'id' is required")
            continue
        if sid in seen_ids:
            problems.add(file, where, f"duplicate section id '{sid}'")
        seen_ids.add(sid)
        where = f"section '{sid}'"
        for key in sorted(set(section) - SECTION_KEYS):
            problems.add(file, where, f"unknown key '{key}'")
        if not isinstance(section.get("title"), str):
            problems.add(file, where, "'title' is required")
        deals = section.get("deals") or []
        if not isinstance(deals, list):
            problems.add(file, where, "'deals' must be a list")
            deals = []
        clean = [validate_deal(d, file, f"{where}, deal #{n}", problems) for n, d in enumerate(deals, 1)]
        out_sections.append({
            "id": sid,
            "title": text_or_empty(section.get("title")) or sid,
            "emoji": text_or_empty(section.get("emoji")),
            "deals": [d for d in clean if d],
        })

    return {
        "year": year,
        "title": text_or_empty(meta.get("title")),
        "intro": text_or_empty(meta.get("intro")),
        "credits": [c.strip() for c in credits if c.strip()],
        "sections": out_sections,
    }


# --------------------------------------------------------------------------- rendering

def esc(text: str) -> str:
    """Keep text from breaking a markdown table row."""
    return text.replace("|", "\\|").replace("\n", " ")


def link_target(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def slug(heading: str) -> str:
    """Match GitHub's heading anchors: 'Courses & Training' -> 'courses--training'."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def fmt_date(day: dt.date, list_year: int) -> str:
    text = f"{day:%b} {day.day}"
    return text if day.year == list_year else f"{text}, {day.year}"


def is_expired(deal, today: dt.date, archive: bool) -> bool:
    return not archive and deal["ends"] is not None and deal["ends"] < today


def dates_cell(deal, year: int, expired: bool) -> str:
    starts, ends = deal["starts"], deal["ends"]
    if expired:
        return f"Ended {fmt_date(ends, year)}"
    if ends is None:
        text = f"From {fmt_date(starts, year)}" if starts else "—"
    elif starts and starts == ends:
        text = f"{fmt_date(ends, year)} only"
    elif starts:
        text = f"{fmt_date(starts, year)} – {fmt_date(ends, year)}"
    else:
        text = fmt_date(ends, year)
    if deal["ends_note"]:
        text += f" ({esc(deal['ends_note'])})"
    return text


def render_section(section, year: int, today: dt.date, archive: bool) -> str:
    deals = section["deals"]
    lines = [f"## {section['title']}", ""]
    if not deals:
        lines.append("_Nothing yet. Know of a deal? See [Contribute](#contribute)._")
        return "\n".join(lines)

    show_focus = any(d["focus"] for d in deals)
    show_notes = any(d["notes"] for d in deals)
    headers = ["Vendor", "Deal", "Code", "Dates"]
    headers += ["Focus"] if show_focus else []
    headers += ["Notes"] if show_notes else []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")

    def sort_key(d):
        return (is_expired(d, today, archive), d["ends"] or dt.date.max, d["vendor"].lower())

    for deal in sorted(deals, key=sort_key):
        expired = is_expired(deal, today, archive)
        strike = (lambda s: f"~~{s}~~") if expired else (lambda s: s)
        marks = ("💖" if deal["taken"] else "") + ("✨" if deal["used"] else "")
        vendor = strike(f"[{esc(deal['vendor'])}]({link_target(deal['url'])})")
        codes = "<br>".join(strike(f"`{c}`") for c in deal["codes"]) or "—"
        cells = [
            f"{vendor} {marks}".strip(),
            strike(esc(deal["deal"])),
            codes,
            dates_cell(deal, year, expired),
        ]
        if show_focus:
            cells.append(esc(deal["focus"]))
        if show_notes:
            cells.append(esc(deal["notes"]))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render(doc, template: str, today: dt.date, updated: str, archive: bool,
           past_years: list[int]) -> str:
    year = doc["year"]
    sections = [s for s in doc["sections"] if s["deals"] or not archive]
    toc = "\n".join(
        f"- {s['emoji'] + ' ' if s['emoji'] else ''}[{s['title']}](#{slug(s['title'])})"
        for s in sections
    )
    credits = "\n".join(f"- {c}" for c in doc["credits"]) or \
        "_Your name could be here. See [Contribute](#contribute)._"
    archives = "\n".join(f"- [{y}](archive/{y}.md)" for y in past_years) or "_None yet._"
    values = {
        "year": str(year),
        "title": doc["title"],
        "intro": doc["intro"],
        "toc": toc,
        "sections": "\n\n".join(render_section(s, year, today, archive) for s in sections),
        "credits": credits,
        "archives": archives,
        "updated": updated,
        "deal_count": str(sum(len(s["deals"]) for s in doc["sections"])),
    }

    def substitute(match):
        key = match.group(1)
        if key not in values:
            raise KeyError(f"unknown placeholder {{{{{key}}}}} in template")
        return values[key]

    text = re.sub(r"\{\{(\w+)\}\}", substitute, template)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def write_if_changed(path: Path, content: str) -> bool:
    """Skip the write when only the 'Last updated' line would differ."""
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if UPDATED_LINE.sub("", old) == UPDATED_LINE.sub("", content):
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--validate", action="store_true", help="check the YAML files without writing anything")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD) to preview expiry")
    args = parser.parse_args(argv)

    now = dt.datetime.now(TIMEZONE)
    today = dt.date.fromisoformat(args.today) if args.today else now.date()
    updated = f"{now:%b} {now.day}, {now:%Y %H:%M %Z}"

    problems = Problems()
    docs = {}
    paths = sorted(p for p in DATA_DIR.glob("*.yaml") if re.fullmatch(r"\d{4}", p.stem))
    if not paths:
        print("No data/<year>.yaml files found.", file=sys.stderr)
        return 1
    for path in paths:
        try:
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=DataLoader)
        except yaml.YAMLError as err:
            problems.add(str(path.relative_to(ROOT)), "YAML syntax", str(err).replace("\n", " "))
            continue
        doc = validate_file(path, data, problems)
        if doc:
            docs[doc["year"]] = doc

    if problems:
        problems.report()
        return 1

    total = sum(len(s["deals"]) for d in docs.values() for s in d["sections"])
    print(f"OK: {total} deals across {len(docs)} year file(s).")
    if args.validate:
        return 0

    current = max(docs)
    past = sorted((y for y in docs if y != current), reverse=True)
    readme_template = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
    archive_template = (TEMPLATE_DIR / "archive.md").read_text(encoding="utf-8")

    changed = []
    if write_if_changed(README, render(docs[current], readme_template, today, updated, False, past)):
        changed.append("README.md")
    for year in past:
        out = ARCHIVE_DIR / f"{year}.md"
        if write_if_changed(out, render(docs[year], archive_template, today, updated, True, [])):
            changed.append(str(out.relative_to(ROOT)))

    print("Wrote: " + ", ".join(changed) if changed else "Nothing changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
