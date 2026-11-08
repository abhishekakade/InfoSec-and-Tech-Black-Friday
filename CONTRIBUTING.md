# Contributing

Thanks for helping out! The README is generated from `data/2026.yaml`, so adding a deal means adding a few lines there. Please don't edit `README.md` directly, because your changes would be overwritten.

## Adding a deal

1. Open [`data/2026.yaml`](data/2026.yaml) (the pencil icon on GitHub works fine).
2. Find the right section (`tools`, `courses`, `labs`, `hardware`, `books`, `wearables`, `games`, `services`) and add an entry under its `deals:`. If the section says `deals: []`, replace the `[]` with your entry.
3. Open a pull request. A check runs automatically and will point out any problems.

```yaml
  - id: courses
    title: Courses & Training
    emoji: 🎓
    deals:
      - vendor: Example Academy
        url: https://example.com/black-friday
        deal: 40% off all courses
        code: "BF26"
        ends: 2026-12-02
        focus: Blue
```

Order doesn't matter. Tables are sorted by end date automatically.

## Fields

| Field | Required | What it is |
|---|---|---|
| `vendor` | yes | Company or product name |
| `url` | yes | Plain link to the deal page. No affiliate, referral, or tracking parameters, and no Amazon links |
| `deal` | yes | Short description, e.g. `40% off all courses` |
| `code` | no | Discount code in quotes. For more than one: `["CODE1", "CODE2"]` |
| `starts` | no | Start date if it hasn't started yet, `YYYY-MM-DD` |
| `ends` | no | End date, `YYYY-MM-DD`. Please include it when the vendor lists one |
| `ends_note` | no | Extra timing detail, e.g. `midnight PST` |
| `focus` | no | `Red`, `Blue`, `Red / Blue`, `Dev`, `Cloud`, `Networking`, `General`, etc. |
| `notes` | no | Anything else worth knowing. Markdown links are fine |

`taken` (💖) and `used` (✨) are the maintainer's personal picks, so please leave them off.

## YAML gotchas

- **Always quote codes.** YAML silently turns `NO`, `YES`, and `ON` into true/false, and `0042` into `42`. The check will catch it, but quoting avoids it.
- **Indent with spaces, not tabs**, and line up with the entries around yours.
- **Quote text that contains `: `** (colon followed by a space), e.g. `vendor: "Book: Second Edition"`.

## Previewing locally (optional)

```sh
pip install -r requirements.txt
python scripts/generate.py --validate            # check for problems
python scripts/generate.py                       # rebuild README.md and archive/
python scripts/generate.py --today 2026-12-02    # preview what expires by a given date
```

## Starting a new year (maintainer)

Copy `data/2026.yaml` to `data/2027.yaml`, update `meta.year`, `meta.title`, and `meta.intro`, and empty each section's `deals:` back to `[]`. The newest year becomes the README automatically, and older years move to `archive/`.
