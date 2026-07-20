"""The shop's small design system — colours and a few reusable pieces.

The whole palette is derived from just two owner-chosen colours: a **brand**
colour (buttons, links, highlights) and a **background** (the page — light or
dark). Everything else — text, cards, borders — is computed from those two so
the result is always legible, whatever colours the owner picks.

The live values arrive from the backend and are published as CSS variables on
the page root (see ``shop.py``); the helpers below simply read those variables,
so a colour change re-paints the whole site with nothing hardcoded.
"""

import reflex as rx

# Colours the components read. Each resolves to a CSS variable set on the page
# root from the owner's saved theme, so changing the theme re-paints everything.
PAPER = "var(--bg)"  # the page the whole app sits on
INK = "var(--fg)"  # primary text
CARD = "var(--card)"  # panel surfaces
BORDER = "var(--border)"  # hairline separators
MUTED = "var(--muted)"  # secondary text
SUBTLE = "var(--subtle)"  # faint fills (inactive chips)
BRAND = "var(--brand)"  # buttons, highlights
BRAND_TEXT = "var(--brand-text)"  # brand colour, tuned to read on a card
BRAND_CONTRAST = "var(--brand-contrast)"  # text/icon on top of the brand colour

SHADOW = "0 1px 3px rgba(0,0,0,0.06)"
CARD_SHADOW = "0 10px 30px -12px rgba(0,0,0,0.25)"

# --- palette derivation ---------------------------------------------------
# Compile-time defaults; the live values come from the backend at runtime.
DEFAULT_BRAND = "#9e7b53"
DEFAULT_BACKGROUND = "#f6f1e9"

# Compile-time default for the sign-in headline; the live value comes from the
# backend and the owner can change it from the UI.
DEFAULT_HEADLINE = "A sua cadeira está à espera"

# Quick-pick presets shown beside the colour pickers (the picker gives full
# freedom; these are just handy starting points across the spectrum).
BRAND_PRESETS = [
    "#9e7b53", "#b45309", "#c2410c", "#dc2626", "#e11d48", "#db2777",
    "#9333ea", "#6d28d9", "#4f46e5", "#2563eb", "#0891b2", "#0d9488",
    "#16a34a", "#65a30d", "#ca8a04", "#0f172a",
]
BACKGROUND_PRESETS = [
    # light papers…
    "#ffffff", "#f6f1e9", "#f5f5f4", "#f1f5f9", "#faf5ff", "#fef2f2", "#f0fdf4",
    # …and dark ones.
    "#0f172a", "#1c1917", "#111827", "#18181b", "#0c0a09", "#1e1b4b", "#022c22",
]

_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Perceived brightness (0=black … 1=white), used to pick readable text."""

    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _rgba(rgb: tuple[int, int, int], alpha: float) -> str:
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


def derive_theme(brand: str, background: str) -> dict[str, str]:
    """Turn two owner-chosen colours into a full, legible palette.

    Text, cards and borders are chosen from the background's brightness, so the
    page reads well whether the owner picked a light or a dark colour. The
    ``accent-*`` keys re-point Radix's own tokens at the brand, so its buttons,
    badges and inputs follow along too.
    """
    bg = _rgb(background)
    br = _rgb(brand)
    dark = _luminance(bg) < 0.5

    fg = (247, 246, 244) if dark else (26, 22, 18)
    card = _mix(bg, _WHITE, 0.06) if dark else _mix(bg, _WHITE, 0.7)
    brand_text = _mix(br, _WHITE, 0.30) if dark else _mix(br, _BLACK, 0.28)
    brand_hover = _mix(br, _WHITE, 0.12) if dark else _mix(br, _BLACK, 0.12)
    brand_contrast = "#ffffff" if _luminance(br) < 0.55 else "#141210"

    return {
        "brand": brand,
        "brand-text": _hex(brand_text),
        "brand-contrast": brand_contrast,
        "bg": background,
        "card": _hex(card),
        "fg": _hex(fg),
        "muted": _rgba(fg, 0.62),
        "border": _rgba(fg, 0.16),
        "subtle": _rgba(fg, 0.06),
        # Radix accent tokens, so its components follow the brand colour.
        "accent-9": brand,
        "accent-10": _hex(brand_hover),
        "accent-11": _hex(brand_text),
        "accent-a11": _hex(brand_text),
        "accent-contrast": brand_contrast,
        "accent-8": _rgba(br, 0.45),
        "accent-a2": _rgba(br, 0.05),
        "accent-a3": _rgba(br, 0.12),
        "accent-a4": _rgba(br, 0.18),
        "accent-a6": _rgba(br, 0.32),
    }


def appearance_of(background: str) -> str:
    """'light' or 'dark', from the background's brightness — drives Radix."""
    return "dark" if _luminance(_rgb(background)) < 0.5 else "light"


def muted(text: str, **props) -> rx.Component:
    props.setdefault("size", "2")
    props.setdefault("color", MUTED)
    return rx.text(text, **props)


def card(*children: rx.Component, **props) -> rx.Component:
    """A clean sheet: the basic surface every panel sits on."""
    props.setdefault("background", CARD)
    props.setdefault("border_radius", "18px")
    props.setdefault("padding", "1.5rem")
    props.setdefault("box_shadow", CARD_SHADOW)
    props.setdefault("width", "100%")
    return rx.box(*children, **props)


def step(number: str, title: str, *body: rx.Component) -> rx.Component:
    """A numbered step: a brand bubble, a title, and its content beneath."""
    bubble = rx.flex(
        rx.text(number, weight="bold", color=BRAND_CONTRAST, size="2"),
        width="1.6rem",
        height="1.6rem",
        align="center",
        justify="center",
        background=BRAND,
        border_radius="50%",
        flex_shrink="0",
    )
    return rx.vstack(
        rx.hstack(bubble, rx.heading(title, size="4", color=INK), align="center", spacing="3"),
        *body,
        spacing="3",
        align="start",
        width="100%",
    )


def panel_title(title: str, subtitle: str = "") -> rx.Component:
    """A heading for a standalone panel (schedule, my appointments, …)."""
    return rx.vstack(
        rx.heading(title, size="5", color=INK),
        rx.cond(subtitle != "", muted(subtitle)),
        spacing="1",
        align="start",
        width="100%",
    )


def empty(message: str) -> rx.Component:
    """The quiet placeholder shown when a list has nothing in it yet."""
    return rx.vstack(
        rx.icon("calendar-off", size=26, color=BRAND),
        muted(message, align="center"),
        spacing="2",
        align="center",
        padding_y="1.5rem",
        width="100%",
    )


def row(*children: rx.Component, **props) -> rx.Component:
    """One line item inside a list card, with a hairline separator above."""
    return rx.hstack(
        *children,
        justify="between",
        align="center",
        width="100%",
        padding_y="0.85rem",
        border_top=f"1px solid {BORDER}",
        **props,
    )
