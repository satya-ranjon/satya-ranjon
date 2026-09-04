#!/usr/bin/env python3
"""Render the language breakdown card, light and dark, as PNGs in this repository.

Why this exists rather than a URL to somebody's card service:

The card that used to sit in the README pointed at github-readme-stats.vercel.app.
That is one free Vercel instance serving an enormous number of profiles, it lives
at its invocation limit, and when it is over quota GitHub's image proxy shows a
broken placeholder. A broken image on a profile you are showing employers is worse
than no image, and no query parameter fixes someone else's rate limit.

So the card is generated here instead. A workflow runs this script, commits the two
PNGs, and the README points at files in this repository. They are served by GitHub's
own CDN, so the card cannot rate-limit, time out, or disappear because a third party
ran out of free tier.

Two other things fall out of owning the renderer:

  * With a token carrying `repo` scope the query sees private repositories, so the
    card reflects the backend work instead of only what happens to be public.
  * The card states its own scope in the footer — "public and private" or "public
    only" — computed from what the query actually returned. It cannot over-claim,
    because the label is derived from the data rather than written by hand.

Design matches scripts/make_banner.py and the portfolio site: ledger palette,
monospaced numerals, a hairline above the footer. Bar segments use GitHub's own
language colours, because those are the colours everyone already reads as "this is
a language chart".

Usage:
    python3 scripts/make_langs_card.py --user satya-ranjon
        Reads the token from $GH_GRAPHQL_TOKEN and writes assets/langs-*.png.

    python3 scripts/make_langs_card.py --fixture tests/langs-fixture.json
        Renders from a saved API response. No network. This is how the layout was
        checked, since the machine that wrote it could not reach api.github.com.

    --ignore html,css
        Drops languages from the chart. Deliberately empty by default: suppressing
        real languages so the mix looks more backend-heavy is the same move as
        padding a resume. Available because it is your profile, not mine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2  # supersampling factor; drawn at 2x, downsampled once at the end
W, H = 520, 195

# The legend is two columns inside a 195px card, which leaves room for four rows
# each. Nine rows put the last one on top of the footer, so the count is capped
# here and anything past it folds into Other rather than overflowing.
MAX_ROWS = 8

LIGHT = dict(
    paper=(237, 241, 246),
    ink=(18, 26, 37),
    rule=(198, 206, 218),
    stamp=(75, 58, 134),
    muted=(90, 102, 117),
    track=(214, 221, 230),
)
DARK = dict(
    paper=(15, 20, 28),
    ink=(231, 236, 243),
    rule=(35, 44, 57),
    stamp=(163, 146, 232),
    muted=(138, 150, 166),
    track=(28, 35, 46),
)

# Font files differ between this machine and the Actions runner, so try in order
# and fail with something readable rather than a stack trace from truetype().
BODY_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        nameWithOwner
        isPrivate
        languages(first: 25, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def resolve_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size * S)
    raise SystemExit(
        "none of these fonts are installed:\n  "
        + "\n  ".join(candidates)
        + "\ninstall fonts-liberation and fonts-dejavu-core, or add a path above."
    )


def fetch(login: str, token: str) -> list[dict]:
    """Page through the user's non-fork repositories they own."""
    repos: list[dict] = []
    after = None
    while True:
        body = json.dumps({"query": QUERY, "variables": {"login": login, "after": after}})
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=body.encode("utf-8"),
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "make-langs-card (satya-ranjon profile)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"github api returned {exc.code}: {detail}") from exc

        if payload.get("errors"):
            raise SystemExit("github api errors: " + json.dumps(payload["errors"], indent=2))

        user = payload.get("data", {}).get("user")
        if user is None:
            raise SystemExit(f"no such user: {login}")

        conn = user["repositories"]
        repos.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            return repos
        after = conn["pageInfo"]["endCursor"]


def aggregate(repos: list[dict], limit: int, ignore: set[str]) -> dict:
    """Sum language bytes across repositories, keep the top `limit`, group the rest."""
    totals: dict[str, int] = {}
    colours: dict[str, str | None] = {}
    counted = 0
    saw_private = False

    for repo in repos:
        edges = repo.get("languages", {}).get("edges") or []
        useful = [e for e in edges if e["node"]["name"].lower() not in ignore]
        if not useful:
            continue
        counted += 1
        saw_private = saw_private or bool(repo.get("isPrivate"))
        for edge in useful:
            name = edge["node"]["name"]
            totals[name] = totals.get(name, 0) + edge["size"]
            colours.setdefault(name, edge["node"].get("color"))

    if not totals:
        raise SystemExit("the query returned no language data at all")

    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    head, tail = ranked[: min(limit, MAX_ROWS)], ranked[min(limit, MAX_ROWS) :]
    # An Other row needs a slot of its own, so give one back if the card is full.
    if tail and len(head) == MAX_ROWS:
        tail = [head.pop()] + tail
    total = sum(totals.values())

    rows = [(name, size, size / total * 100, colours.get(name)) for name, size in head]
    if tail:
        other = sum(size for _, size in tail)
        rows.append(("Other", other, other / total * 100, None))

    return {
        "rows": rows,
        "repos": counted,
        "scope": "public and private" if saw_private else "public only",
    }


def hexcolour(value: str | None, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    """GitHub's own language colour, e.g. '#3178c6'. Some languages have none."""
    if not value:
        return fallback
    v = value.lstrip("#")
    if len(v) != 6:
        return fallback
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except ValueError:
        return fallback


MARK_START = "<!-- langs:start -->"
MARK_END = "<!-- langs:end -->"


def readme_block(data: dict) -> str:
    """The <picture> element, with alt text carrying the actual numbers.

    A static image is opaque to a screen reader, so the figures go in the alt
    attribute rather than a generic 'language chart' label. Regenerating the block
    alongside the PNGs is also the reason the markup and the images can never
    disagree: they are written in the same commit.
    """
    top = ", ".join(f"{name} {pct:.1f}%" for name, _, pct, _ in data["rows"][:4])
    alt = escape(
        f"Language breakdown across {data['repos']} repositories "
        f"({data['scope']}): {top}, and others.",
        quote=True,
    )
    return "\n".join(
        [
            MARK_START,
            "<picture>",
            '  <source media="(prefers-color-scheme: dark)" srcset="./assets/langs-dark.png">',
            f'  <img src="./assets/langs-light.png" alt="{alt}" height="195">',
            "</picture>",
            MARK_END,
        ]
    )


def patch_readme(path: Path, data: dict) -> None:
    """Rewrite whatever sits between the two marker comments.

    The markers are HTML comments, so an empty pair renders as nothing on GitHub.
    That is what lets the README be committed before the images exist without ever
    showing a broken image: the first workflow run fills the markers and adds the
    PNGs in one commit.
    """
    if not path.exists():
        print(f"no {path.name} to patch")
        return
    src = path.read_text(encoding="utf-8")
    if MARK_START not in src or MARK_END not in src:
        print(f"markers {MARK_START} / {MARK_END} not found in {path.name}; left alone")
        return
    pre, rest = src.split(MARK_START, 1)
    _, post = rest.split(MARK_END, 1)
    new = pre + readme_block(data) + post
    if new == src:
        print(f"{path.name} already current")
        return
    path.write_text(new, encoding="utf-8")
    print(f"patched {path.name}")


def render(data: dict, palette: dict, out: Path) -> None:
    c = palette
    img = Image.new("RGB", (W * S, H * S), c["paper"])
    d = ImageDraw.Draw(img)

    f_head = resolve_font(MONO_CANDIDATES, 11)
    f_name = resolve_font(BODY_CANDIDATES, 13)
    f_pct = resolve_font(MONO_CANDIDATES, 12)
    f_foot = resolve_font(MONO_CANDIDATES, 10)

    def px(x: int, y: int) -> tuple[int, int]:
        return (x * S, y * S)

    def text(x, y, s, font, colour):
        d.text(px(x, y), s, font=font, fill=colour)

    def rule(x0, x1, y, colour, width=1):
        d.line([px(x0, y), px(x1, y)], fill=colour, width=width * S)

    # Border. Rounded corners need Pillow >= 8.2; a square box is a fine fallback.
    box = [px(0, 0), px(W - 1, H - 1)]
    try:
        d.rounded_rectangle(box, radius=6 * S, outline=c["rule"], width=1 * S)
    except AttributeError:
        d.rectangle(box, outline=c["rule"], width=1 * S)

    left, right = 20, W - 20
    text(left, 16, "LANGUAGES", f_head, c["muted"])

    # Stacked bar. Widths are laid down cumulatively from a float cursor so the
    # segments cannot drift apart or leave a gap at the right edge.
    bar_y, bar_h = 40, 9
    d.rectangle([px(left, bar_y), px(right, bar_y + bar_h)], fill=c["track"])
    x = float(left)
    span = right - left
    for i, (_, _, pct, colour) in enumerate(data["rows"]):
        w = span * pct / 100
        end = right if i == len(data["rows"]) - 1 else x + w
        if end - x >= 0.5:
            d.rectangle(
                [(int(x * S), bar_y * S), (int(end * S), (bar_y + bar_h) * S)],
                fill=hexcolour(colour, c["muted"]),
            )
        x = end

    # Legend, two columns. Percentages are right-aligned against a fixed edge so
    # the decimal points line up down each column.
    rows = data["rows"]
    if len(rows) > MAX_ROWS:
        raise SystemExit(
            f"{len(rows)} legend rows will not fit in a {H}px card; MAX_ROWS is {MAX_ROWS}."
        )
    col_x = [left, left + 250]
    rows_per_col = (len(rows) + 1) // 2
    for i, (name, _, pct, colour) in enumerate(rows):
        cx = col_x[i // rows_per_col]
        y = 68 + (i % rows_per_col) * 25
        d.ellipse([px(cx, y + 4), px(cx + 7, y + 11)], fill=hexcolour(colour, c["muted"]))
        text(cx + 14, y, name, f_name, c["ink"])
        label = f"{pct:.1f}%"
        w = d.textlength(label, font=f_pct) / S
        text(cx + 210 - w, y + 1, label, f_pct, c["muted"])

    plural = "repository" if data["repos"] == 1 else "repositories"
    rule(left, right, H - 32, c["rule"])
    text(left, H - 24, f"{data['repos']} {plural} · {data['scope']}", f_foot, c["muted"])
    d.ellipse([px(right - 7, H - 21), px(right, H - 14)], fill=c["stamp"])

    out.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(out, "PNG", optimize=True)
    print(f"wrote {out.name} — {W}x{H}, {out.stat().st_size // 1024} KB")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default="satya-ranjon")
    ap.add_argument("--fixture", type=Path, help="render from a saved API response, no network")
    ap.add_argument("--out", type=Path, default=root / "assets")
    ap.add_argument("--limit", type=int, default=8, help="languages shown before grouping as Other")
    ap.add_argument("--ignore", default="", help="comma separated languages to drop; empty by default")
    ap.add_argument("--readme", type=Path, default=root / "README.md")
    ap.add_argument("--no-readme", action="store_true", help="render the images only")
    args = ap.parse_args()

    ignore = {s.strip().lower() for s in args.ignore.split(",") if s.strip()}

    if args.fixture:
        raw = json.loads(args.fixture.read_text(encoding="utf-8"))
        # A fixture may be a bare list of repository nodes, or an object wrapping
        # them so it has somewhere to carry a note about being synthetic.
        repos = raw["nodes"] if isinstance(raw, dict) else raw
    else:
        token = os.environ.get("GH_GRAPHQL_TOKEN", "").strip()
        if not token:
            sys.exit(
                "GH_GRAPHQL_TOKEN is empty.\n"
                "\n"
                "In the workflow it comes from a repository secret named STATS_TOKEN, so\n"
                "an empty value means the secret does not exist yet or is named something\n"
                "else. To add it:\n"
                "\n"
                "  Settings -> Secrets and variables -> Actions -> Secrets tab\n"
                "  -> New repository secret -> name it exactly STATS_TOKEN\n"
                "  -> value is a classic personal access token with the `repo` scope\n"
                "\n"
                "Three things that look right but are not: the Variables tab instead of\n"
                "the Secrets tab, a Dependabot or Codespaces secret instead of an Actions\n"
                "one, and a trailing space in the name.\n"
                "\n"
                "To run this by hand instead:\n"
                "  GH_GRAPHQL_TOKEN=ghp_... python3 scripts/make_langs_card.py\n"
            )
        repos = fetch(args.user, token)

    data = aggregate(repos, limit=args.limit, ignore=ignore)
    print(f"{data['repos']} repositories · {data['scope']} · {len(data['rows'])} rows")
    for name, size, pct, _ in data["rows"]:
        print(f"  {name:<16} {pct:5.1f}%  {size:>10,} bytes")
    print(f"  {'sum':<16} {sum(r[2] for r in data['rows']):5.1f}%")

    render(data, LIGHT, args.out / "langs-light.png")
    render(data, DARK, args.out / "langs-dark.png")
    if not args.no_readme:
        patch_readme(args.readme, data)


if __name__ == "__main__":
    main()
