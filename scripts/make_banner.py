#!/usr/bin/env python3
"""Generate the profile header image, light and dark.

The header this replaces was a stock wallpaper of technology logos — Go, Kafka,
Swift, Ruby, Vue, Nginx, Jenkins — none of which are part of the stack this
profile claims. A header that advertises skills you would not put on a resume is
worse than no header, so this one carries only true information: who, where, what
I work on, and the four open entries from the ledger on the portfolio site.

The design is deliberately the same as satya-ranjan's portfolio: the ledger
palette, an expanded grotesque for the name, a monospaced rail for sequence
numbers and state. GitHub and the site then look like one person's work.

Two variants are produced because GitHub renders READMEs in both light and dark
themes and the README selects between them with prefers-color-scheme. A single
light-only banner looks broken for the roughly half of developers on dark mode.

Type is approximated. Archivo and IBM Plex Mono are not installed here, so the
display face is Liberation Sans Bold stretched horizontally by 9% to stand in for
Archivo's width axis, exactly as scripts/make_og.py does in the portfolio repo.

Run: python3 scripts/make_banner.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2  # supersampling factor; text is drawn at 2x then downsampled

W, H = 1400, 350

LIGHT = dict(
    paper=(237, 241, 246),
    ink=(18, 26, 37),
    rule=(198, 206, 218),
    stamp=(75, 58, 134),
    muted=(90, 102, 117),
)
DARK = dict(
    paper=(15, 20, 28),
    ink=(231, 236, 243),
    rule=(35, 44, 57),
    stamp=(163, 146, 232),
    muted=(138, 150, 166),
)

DISPLAY_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
BODY = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

STRETCH = 1.09  # stands in for Archivo wdth 115

NAME = "Satya Ranjan DebSharma"
EYEBROW = "SOFTWARE ENGINEER  ·  DHAKA, BANGLADESH"
STATEMENT = (
    "I build backends that have to stay correct when two people "
    "touch the same row at the same time."
)

# The open entries from the portfolio ledger, in the same order the site shows
# them. Sequence numbers are the site's, so the two cannot disagree.
LEDGER = [
    ("008", "FieldForge", "open"),
    ("007", "B.Sc. Computer Science", "open"),
    ("005", "VegMove", "open"),
    ("003", "Software Engineer, Techsfera", "open"),
]

OUT = Path(__file__).resolve().parent.parent / "assets"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size * S)


class Banner:
    def __init__(self, palette: dict):
        self.c = palette
        self.img = Image.new("RGB", (W * S, H * S), palette["paper"])
        self.d = ImageDraw.Draw(self.img)

    def rule(self, x0: int, x1: int, y: int, colour=None, width: int = 1) -> None:
        self.d.line(
            [(x0 * S, y * S), (x1 * S, y * S)],
            fill=colour or self.c["rule"],
            width=width * S,
        )

    def text(self, x: int, y: int, s: str, f: ImageFont.FreeTypeFont, colour=None) -> None:
        self.d.text((x * S, y * S), s, font=f, fill=colour or self.c["ink"])

    def wide(self, x: int, y: int, s: str, f: ImageFont.FreeTypeFont, colour=None) -> None:
        """Display type, stretched horizontally to approximate Archivo expanded."""
        box = f.getbbox(s)
        layer = Image.new("RGBA", (box[2] + 16 * S, box[3] + 16 * S), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((0, 0), s, font=f, fill=colour or self.c["ink"])
        layer = layer.resize((int(layer.width * STRETCH), layer.height), Image.LANCZOS)
        self.img.paste(layer, (x * S, y * S), layer)

    def dot(self, x: int, y: int, r: int, colour) -> None:
        self.d.ellipse([(x * S, y * S), ((x + r) * S, (y + r) * S)], fill=colour)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.img.resize((W, H), Image.LANCZOS).save(path, "PNG", optimize=True)
        print(f"wrote {path.name} — {W}x{H}, {path.stat().st_size // 1024} KB")


def compose(palette: dict) -> Banner:
    b = Banner(palette)
    left, right = 72, W - 72
    f_name = font(DISPLAY_BOLD, 50)
    f_body = font(BODY, 17)
    f_mono = font(MONO, 13)
    f_mono_head = font(MONO, 12)

    # Header hairline, with a short stamp-violet segment at the left the way the
    # site header marks the active page.
    b.rule(left, right, 44)
    b.rule(left, left + 52, 44, palette["stamp"], width=2)

    # Identity block.
    b.text(left, 86, EYEBROW, f_mono, palette["muted"])
    b.wide(left, 112, NAME, f_name)

    # Statement, wrapped by hand to two balanced lines rather than measured, so the
    # break lands somewhere sensible instead of wherever the measure happens to fall.
    b.text(left, 196, "I build backends that have to stay correct when two people", f_body, palette["muted"])
    b.text(left, 222, "touch the same row at the same time.", f_body, palette["muted"])

    # The ledger, right-hand side. Column positions are fixed so the sequence
    # numbers, titles and state chips align down the block — a ledger whose digits
    # do not line up is a broken ledger.
    lx = 880
    b.text(lx, 86, "OPEN ENTRIES", f_mono_head, palette["muted"])
    b.rule(lx, right, 104)
    y = 118
    for seq, title, state in LEDGER:
        b.text(lx, y, seq, f_mono, palette["ink"])
        b.text(lx + 56, y, title, f_mono, palette["ink"])
        b.dot(right - 46, y + 5, 6, palette["stamp"])
        b.text(right - 34, y, state, f_mono, palette["stamp"])
        y += 26
    b.rule(lx, right, y + 4)

    # Closing double rule, the way a ledger marks a total.
    b.rule(left, right, 300)
    b.rule(left, right, 303)
    b.text(left, 316, "github.com/satya-ranjon", f_mono, palette["muted"])
    return b


def main() -> None:
    compose(LIGHT).save(OUT / "banner-light.png")
    compose(DARK).save(OUT / "banner-dark.png")


if __name__ == "__main__":
    main()
