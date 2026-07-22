"""All page state: authentication, the user's role, booking, and appointments."""

import asyncio
import base64
import dataclasses
import os
from calendar import monthrange
from datetime import date, timedelta
from itertools import groupby

import httpx
import jwt
import reflex as rx

from shop.ui import (
    BACKGROUND_PRESETS,
    BRAND_PRESETS,
    DEFAULT_BACKGROUND,
    DEFAULT_BRAND,
    DEFAULT_HEADLINE,
    appearance_of,
    derive_theme,
)

# Where the booking API lives (override with API_URL in another deployment).
API_URL = os.environ.get("API_URL", "http://localhost:8000")

# Reflex's own backend — the same origin the browser already connects to for
# websocket state sync (see rxconfig.py; frontend and backend share one port
# in production). The shop's logo is proxied through here too (see
# shop/api.py), so the booking API itself never needs to be reachable from
# the browser just to show it.
REFLEX_API_URL = os.environ.get("REFLEX_API_URL", "http://localhost:3000")

# Must match the backend's JWT_SECRET (see backend/app/security.py) — lets us
# verify an access token's signature locally, with no network call, so we
# can show the right view (logged out / customer / barber / admin) almost
# immediately after a page reload instead of waiting on a round-trip to
# /auth/me first. This is purely an optimistic, faster first paint: the
# backend never trusts these claims either — every real request re-checks
# the user/role server-side regardless of what the token says.
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"


def _decode_access_token(token: str) -> dict | None:
    """Verify and decode an access token locally; None if invalid/expired/wrong purpose."""
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if claims.get("purpose") != "access":
        return None
    return claims


# Matches the backend's app.routers.appointments.STANDING_SLOT_CONFLICT — a
# machine-readable error code, not a message string, so this check can't be
# broken by future wording changes on either side.
STANDING_SLOT_CONFLICT = "standing_slot_conflict"


def _error_code(resp: httpx.Response) -> str | None:
    """The structured error code from a JSON error body, if any (e.g. {"detail": {"code": ...}})."""
    try:
        detail = resp.json().get("detail")
    except ValueError:
        return None
    return detail.get("code") if isinstance(detail, dict) else None


# Browser-facing URL of the admin console (the backend serves it at /admin).
# Empty by default — the admin console is optional to expose publicly at
# all; when empty, the UI hides the link instead of showing a dead one.
ADMIN_URL = os.environ.get("ADMIN_URL", "")

# In dev, the compose file points this at Mailpit so the verify banner can link
# straight to the caught email. Unset in production, where real email is sent.
MAIL_INBOX_URL = os.environ.get("MAIL_INBOX_URL", "")

# Flash-message fields that show a temporary callout somewhere in the UI.
# refresh() clears them all on every page load/reconnect as a safety net, and
# clear_message_after() auto-dismisses each one a few seconds after it's set,
# so a message never gets stuck on screen (e.g. after a crashed request).
FLASH_FIELDS = (
    "booking_msg",
    "manual_msg",
    "hours_msg",
    "service_msg",
    "recurring_msg",
    "logo_msg",
    "theme_msg",
    "profile_msg",
    "pw_msg",
)


# Reflex creates a fresh State per browser tab, so without this, every new
# tab/refresh starts from the class-level defaults below and visibly flashes
# them until on_load's API calls resolve. This process-wide, in-memory cache
# holds the last successfully-fetched public shop data (name, theme, logo
# version); new State instances seed their fields from it instead of the
# generic defaults, so only the very first visitor after a cold start sees a
# flash — everyone else gets last-known-good data immediately, still
# refreshed in the background by init()/save_theme() exactly as before. This
# is the standard "stale-while-revalidate" pattern: instant render from cache,
# always re-verified against the real API afterwards. It's a single dict in
# this worker's own memory (no Redis) — fine because frontend.replicas is
# pinned to 1 (see values.yaml), and it resets on pod restart same as today.
_public_cache: dict[str, str] = {}


def _cached(key: str, default: str) -> str:
    return _public_cache.get(key, default)


@dataclasses.dataclass
class Barber:
    id: int
    name: str
    allow_recurring: bool = False
    max_recurring_weeks: int = 12


@dataclasses.dataclass
class Service:
    id: int
    name: str
    duration_minutes: int
    is_active: bool = True


@dataclasses.dataclass
class Day:
    iso: str  # "2026-08-02"
    dow: str  # "Mon"
    dom: str  # "02"


@dataclasses.dataclass
class Slot:
    value: str  # "2026-08-02T09:00:00"
    label: str  # "09:00"


@dataclasses.dataclass
class Appt:
    id: int
    time: str  # "09:00"
    barber_name: str
    group_id: str = ""  # non-empty when part of a weekly series


@dataclasses.dataclass
class ScheduledAppt:
    id: int
    time: str  # "09:00"
    customer_name: str
    customer_email: str
    customer_phone: str = ""
    service_id: int = 0
    service_name: str = ""
    duration: int = 30
    group_id: str = ""  # non-empty when part of a weekly series


@dataclasses.dataclass
class ApptGroup:
    label: str  # "Hoje" / "Seg, 20 jul"
    appts: list[Appt]


@dataclasses.dataclass
class ScheduleGroup:
    iso: str  # "2026-07-20" — the day this group belongs to
    label: str
    appts: list[ScheduledAppt]


@dataclasses.dataclass
class RecurringSeriesEntry:
    """One "Horário Fixo" — a standing weekly booking, perpetual or bounded."""

    id: str  # the recurrence_group_id; also what /appointments/series/{id} cancels
    kind: str  # "perpetual" | "bounded"
    weekday_label: str  # "Segunda"
    time_label: str  # "10:00"
    limit_label: str  # "Sem data limite" or "Até 12/09/2026"
    service_name: str
    barber_name: str
    customer_name: str
    customer_email: str = ""  # "" for a walk-in with no account
    customer_phone: str = ""  # "" for a walk-in, or an account with none on file


@dataclasses.dataclass
class DayTab:
    """One day in the barber's week strip: a date with how many are booked."""

    iso: str
    dow: str  # "Seg"
    dom: str  # "20"
    count: int


@dataclasses.dataclass
class HoursRow:
    """One weekday in the working-hours editor."""

    weekday: str  # backend enum value, e.g. "Monday"
    label: str  # "Segunda"
    open: bool
    start: str  # "09:00"
    end: str  # "17:00"
    break_start: str  # "12:00" or ""
    break_end: str  # "13:00" or ""


@dataclasses.dataclass
class CalCell:
    """One cell in the month calendar: a day, or a blank pad before the 1st."""

    iso: str  # "2026-07-21", or "" for a blank pad
    dom: str  # "21", or "" for a pad
    disabled: bool  # a pad, or a day in the past


# Backend weekday value → Portuguese label, in Monday-first order.
_WEEKDAYS = [
    ("Monday", "Segunda"),
    ("Tuesday", "Terça"),
    ("Wednesday", "Quarta"),
    ("Thursday", "Quinta"),
    ("Friday", "Sexta"),
    ("Saturday", "Sábado"),
    ("Sunday", "Domingo"),
]


# Portuguese day/month names, so dates read naturally without a system locale.
_DOW = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]  # Monday-first
_MON = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_MON_FULL = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _day_label(d: date) -> str:
    """A friendly heading for a day's group of appointments."""
    today = date.today()
    if d == today:
        return "Hoje"
    if d == today + timedelta(days=1):
        return "Amanhã"
    return f"{_DOW[d.weekday()]}, {d.day:02d} {_MON[d.month - 1]}"


def _by_day(rows: list[dict]):
    """Group API rows (sorted by start_at) into (iso, label, rows) per day."""
    for iso_day, day_rows in groupby(rows, key=lambda r: r["start_at"][:10]):
        yield iso_day, _day_label(date.fromisoformat(iso_day)), list(day_rows)


class State(rx.State):
    shop_name: str = rx.field(default_factory=lambda: _cached("shop_name", "Barbearia"))
    error: str = ""
    mail_inbox_url: str = MAIL_INBOX_URL  # dev only; empty in production
    admin_url: str = ADMIN_URL  # browser-facing link to the backend admin console

    # --- authentication --------------------------------------------------
    token: str = rx.LocalStorage("")  # persists across page reloads
    user_name: str = ""
    is_admin: bool = False
    is_verified: bool = False
    barber_id: int = 0  # > 0 when the logged-in user is a barber

    # True once we know which view to show (logged out / customer / barber /
    # admin) — either from a fast local JWT decode or, for a guest, right
    # away. Gates the UI so nothing renders with a wrong/default shell for a
    # moment; see refresh() and shop.py's body()/brand().
    ui_ready: bool = False

    auth_mode: str = "login"  # "login", "register", or "forgot"
    form_email: str = ""
    form_name: str = ""
    form_password: str = ""
    auth_error: str = ""

    # --- password reset (from email link) --------------------------------
    reset_token: str = ""
    reset_new_password: str = ""
    reset_msg: str = ""
    reset_done: bool = False

    # --- email verification (from email link) -----------------------------
    verify_msg: str = ""
    verify_done: bool = False

    # --- password change (logged-in) ------------------------------------
    pw_current: str = ""
    pw_new: str = ""
    pw_msg: str = ""

    # --- profile (edit your own name / phone) ----------------------------
    profile_name: str = ""
    profile_phone: str = ""
    profile_msg: str = ""

    # --- booking ---------------------------------------------------------
    barbers: list[Barber] = []
    services: list[Service] = []  # active services of the selected chair (customer picks one)
    slots: list[Slot] = []
    selected_barber: int = 0
    selected_service: int = 0
    selected_date: str = ""
    selected_slot: str = ""
    repeat_weeks: str = "1"  # customer's weekly-repeat choice (only if the chair allows it)
    perpetual: bool = False  # "repeat every week, forever" — mutually exclusive with repeat_weeks
    loading_slots: bool = False
    booking_msg: str = ""
    booking_msg_color: str = "blue"  # "tomato" for cancellations, "blue" otherwise
    needs_verify: bool = False

    # --- booking on someone's behalf (barber / admin) --------------------
    manual_name: str = ""
    manual_email: str = ""
    manual_msg: str = ""
    cal_month: str = ""  # first-of-month shown in the manual-booking calendar

    # --- appointments ----------------------------------------------------
    my_appointments: list[ApptGroup] = []
    schedule: list[ScheduleGroup] = []
    recurring_series: list[RecurringSeriesEntry] = []  # every "Horário Fixo", any role
    admin_barber: int = 0
    selected_day: str = ""  # iso day chosen in the agenda's booked-day strip

    # --- working hours (barber / admin edits a chair's weekly schedule) ---
    hours: list[HoursRow] = []
    hours_msg: str = ""

    # --- services + recurrence (barber configures the chair being edited) -
    edit_services: list[Service] = []  # every service, active or not, for the editor
    _next_local_id: int = -1  # counter for unsaved services (negative = not yet in DB)
    new_service_name: str = ""
    new_service_minutes: str = "30"
    service_msg: str = ""
    duration_options: list[str] = ["10", "15", "20", "30", "45", "60", "90", "120"]
    allow_recurring: bool = False  # whether this chair lets customers repeat weekly
    max_recurring_weeks: str = "12"
    recurring_msg: str = ""

    # --- appearance (owner picks two colours; the rest is derived, saved shop-wide) -
    # Seeded from _public_cache (see above) so a warm worker skips the flash
    # of these generic colours/text on every new tab; still refreshed by
    # init()/save_theme() same as before.
    brand: str = rx.field(default_factory=lambda: _cached("brand", DEFAULT_BRAND))
    background: str = rx.field(default_factory=lambda: _cached("background", DEFAULT_BACKGROUND))
    headline: str = rx.field(default_factory=lambda: _cached("headline", DEFAULT_HEADLINE))
    theme_msg: str = ""
    brand_presets: list[str] = BRAND_PRESETS
    background_presets: list[str] = BACKGROUND_PRESETS

    # --- logo (stored in the backend DB; changeable live, no restart) ----
    logo_version: str = rx.field(default_factory=lambda: _cached("logo_version", ""))
    logo_msg: str = ""
    # Pending logo: held in state until the owner clicks "Guardar".
    _pending_logo_b64: str = ""
    _pending_logo_name: str = ""
    _pending_logo_type: str = ""

    # --- computed --------------------------------------------------------
    @rx.var
    def theme_css(self) -> str:
        """A CSS rule that publishes the derived palette as variables.

        Injected into a live ``<style>`` tag and scoped to ``.shop-root``, so
        the owner's two colours cascade to every element — Radix components
        included — and a change re-themes the whole page at once.
        """
        body = ";".join(
            f"--{k}:{v}" for k, v in derive_theme(self.brand, self.background).items()
        )
        return f".shop-root{{{body}}}"

    @rx.var
    def is_dark(self) -> bool:
        """True when the chosen background is dark (drives the color mode)."""
        return appearance_of(self.background) == "dark"

    @rx.var
    def logo_src(self) -> str:
        """Show pending upload as preview, or the live backend logo."""
        if self._pending_logo_b64:
            return f"data:{self._pending_logo_type};base64,{self._pending_logo_b64}"
        return f"{REFLEX_API_URL}/logo?v={self.logo_version}"

    @rx.var
    def logged_in(self) -> bool:
        return self.token != ""

    @rx.var
    def role(self) -> str:
        if self.is_admin:
            return "admin"
        if self.barber_id > 0:
            return "barber"
        return "customer"

    @rx.var
    def can_book(self) -> bool:
        return self.selected_slot != ""

    @rx.var
    def barber_allows_recurring(self) -> bool:
        """Whether the chair being booked lets customers repeat weekly."""
        return next(
            (b.allow_recurring for b in self.barbers if b.id == self.selected_barber), False
        )

    @rx.var
    def repeat_options(self) -> list[str]:
        """1..N weeks, where N is the chair's owner-set cap."""
        cap = next(
            (b.max_recurring_weeks for b in self.barbers if b.id == self.selected_barber), 12
        )
        return [str(i) for i in range(1, cap + 1)]

    @rx.var
    def max_weeks_options(self) -> list[str]:
        """Choices for the owner's recurrence cap (1..52 weeks)."""
        return [str(i) for i in (2, 4, 6, 8, 12, 16, 24, 52)]

    @rx.var
    def can_book_manual(self) -> bool:
        # A slot plus at least a name or an account email to book against.
        return self.selected_slot != "" and (self.manual_name != "" or self.manual_email != "")

    @rx.var
    def days(self) -> list[Day]:
        today = date.today()
        return [
            Day(
                iso=(day := today + timedelta(days=i)).isoformat(),
                dow=_DOW[day.weekday()],
                dom=day.strftime("%d"),
            )
            for i in range(14)
        ]

    def _cal_anchor(self) -> date:
        """First of the month currently shown in the calendar (defaults to now)."""
        if self.cal_month:
            return date.fromisoformat(self.cal_month)
        return date.today().replace(day=1)

    @rx.var
    def cal_title(self) -> str:
        d = self._cal_anchor()
        return f"{_MON_FULL[d.month - 1]} {d.year}"

    @rx.var
    def cal_weekdays(self) -> list[str]:
        return _DOW  # Monday-first headers

    @rx.var
    def cal_cells(self) -> list[CalCell]:
        """The month laid out as whole weeks: blank pads, then each day."""
        first = self._cal_anchor()
        today = date.today()
        cells = [CalCell(iso="", dom="", disabled=True) for _ in range(first.weekday())]
        for dnum in range(1, monthrange(first.year, first.month)[1] + 1):
            d = first.replace(day=dnum)
            cells.append(CalCell(iso=d.isoformat(), dom=str(dnum), disabled=d < today))
        while len(cells) % 7:  # trailing pad so the grid stays rectangular
            cells.append(CalCell(iso="", dom="", disabled=True))
        return cells

    @rx.var
    def can_cal_prev(self) -> bool:
        """Don't page back before this month — booking is only ever forward."""
        return self._cal_anchor() > date.today().replace(day=1)

    # The agenda strip shows only days that actually have bookings, however far
    # ahead they are — so a booking made months out is a chip, not hidden. The
    # agenda is read-only; new bookings are made in the scheduling card.
    @rx.var
    def schedule_tabs(self) -> list[DayTab]:
        return [
            DayTab(
                iso=g.iso,
                dow=_DOW[(d := date.fromisoformat(g.iso)).weekday()],
                dom=f"{d.day:02d}",
                count=len(g.appts),
            )
            for g in self.schedule
        ]

    @rx.var
    def selected_day_appts(self) -> list[ScheduledAppt]:
        for group in self.schedule:
            if group.iso == self.selected_day:
                return group.appts
        return []

    @rx.var
    def selected_day_label(self) -> str:
        if not self.selected_day:
            return ""
        return _day_label(date.fromisoformat(self.selected_day))

    @rx.event
    def select_schedule_day(self, iso: str):
        self.selected_day = iso

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    # --- loading ---------------------------------------------------------
    @rx.event
    async def init(self):
        """Public data everyone sees: the shop name and its barbers."""
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            try:
                self.shop_name = (await client.get("/health")).json()["shop"]
                _public_cache["shop_name"] = self.shop_name
                rows = (await client.get("/barbers")).json()
                self.barbers = [
                    Barber(
                        id=r["id"],
                        name=r["name"],
                        allow_recurring=r.get("allow_recurring", False),
                        max_recurring_weeks=r.get("max_recurring_weeks", 12),
                    )
                    for r in rows
                ]
                if self.barbers and not self.selected_barber:
                    self.selected_barber = self.barbers[0].id
                if self.selected_barber:
                    await self._load_services(client, self.selected_barber)
                await self._load_theme(client)
            except (httpx.HTTPError, KeyError):
                self.error = "Não foi possível contactar a barbearia. A API está a funcionar?"

    @rx.event
    async def refresh(self):
        """Load the data the current user needs, based on their role.

        First decodes the access token locally (no network call) so we can
        set is_admin/barber_id and flip ui_ready almost immediately — this
        is what lets the UI show the right shell right after reload instead
        of waiting on the slower /auth/me round-trip below. That round-trip
        still happens and remains the source of truth: if the token was
        revoked or its claims are stale, logout() corrects the view again.
        """
        if not self.token:
            self.ui_ready = True
            return

        for field in FLASH_FIELDS:  # never let a stuck popup survive a reload
            setattr(self, field, "")

        claims = _decode_access_token(self.token)
        if claims is None:  # locally-verifiable as bad: expired, tampered, wrong secret
            self.logout()
            self.ui_ready = True
            return
        self.is_admin = bool(claims.get("is_admin", False))
        self.barber_id = int(claims.get("barber_id", 0))
        self.ui_ready = True
        yield  # push the fast, locally-decoded shell to the client right away

        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            me = await client.get("/auth/me")
            if me.status_code != 200:  # token expired or invalid
                self.logout()
                return
            user = me.json()
            self.user_name = user["full_name"]
            self.is_admin = user["is_admin"]
            self.is_verified = user["is_verified"]
            self.profile_name = user["full_name"]
            self.profile_phone = user["phone"] or ""

            mine = await client.get("/barbers/me")
            self.barber_id = mine.json()["id"] if mine.status_code == 200 else 0

            if self.is_admin:
                self.admin_barber = self.barbers[0].id if self.barbers else 0
                self.selected_barber = self.admin_barber
                await self._load_schedule(client, self.admin_barber)
                await self._load_hours(client, self.admin_barber)
                await self._load_services(client, self.admin_barber)
                await self._load_recurring_series(client)
            elif self.barber_id:
                self.selected_barber = self.barber_id
                await self._load_schedule(client, self.barber_id)
                await self._load_hours(client, self.barber_id)
                await self._load_services(client, self.barber_id)
                await self._load_recurring_series(client)
            else:
                await self._load_my_appointments(client)
                await self._load_recurring_series(client)

    @rx.event(background=True)
    async def clear_message_after(self, attr: str, value: str, seconds: float = 4.0):
        """Auto-dismiss a flash message a few seconds after it's shown.

        Only clears if ``attr`` still holds the exact ``value`` we scheduled
        this for — if a newer message replaced it in the meantime, that one
        is left alone (it has its own clear_message_after in flight).
        """
        if not value:
            return
        await asyncio.sleep(seconds)
        async with self:
            if getattr(self, attr) == value:
                setattr(self, attr, "")

    async def _load_my_appointments(self, client: httpx.AsyncClient):
        rows = (await client.get("/appointments")).json()
        names = {b.id: b.name for b in self.barbers}
        self.my_appointments = [
            ApptGroup(
                label=label,
                appts=[
                    Appt(
                        id=r["id"],
                        time=r["start_at"][11:16],
                        barber_name=names.get(r["barber_id"], "Barbeiro"),
                        group_id=r.get("recurrence_group_id") or "",
                    )
                    for r in day_rows
                ],
            )
            for _iso, label, day_rows in _by_day(rows)
        ]

    async def _load_recurring_series(self, client: httpx.AsyncClient):
        """Every "Horário Fixo" (standing weekly booking) visible to this user."""
        rows = (await client.get("/appointments/recurring-series")).json()
        self.recurring_series = [
            RecurringSeriesEntry(
                id=r["id"],
                kind=r["kind"],
                weekday_label=_WEEKDAYS[
                    date.fromisoformat(r["anchor_start_at"][:10]).weekday()
                ][1],
                time_label=r["anchor_start_at"][11:16],
                limit_label=(
                    "Sem data limite"
                    if r["kind"] == "perpetual"
                    else f"Até {date.fromisoformat(r['ends_at']).strftime('%d/%m/%Y')}"
                ),
                service_name=r.get("service_name") or "",
                barber_name=r.get("barber_name") or "",
                customer_name=r.get("customer_name") or "",
                customer_email=r.get("customer_email") or "",
                customer_phone=r.get("customer_phone") or "",
            )
            for r in rows
        ]


    async def _load_services(self, client: httpx.AsyncClient, barber_id: int):
        """Load a chair's active services and keep the customer's pick valid."""
        if not barber_id:
            self.services = []
            self.selected_service = 0
            return
        rows = (await client.get(f"/barbers/{barber_id}/services")).json()
        self.services = [
            Service(id=r["id"], name=r["name"], duration_minutes=r["duration_minutes"])
            for r in rows
        ]
        ids = {s.id for s in self.services}
        if self.selected_service not in ids:
            self.selected_service = self.services[0].id if self.services else 0
        self.repeat_weeks = "1"
        self.perpetual = False

    async def _load_services_editor(self, client: httpx.AsyncClient, barber_id: int):
        """Load every service (active or not) into the barber's services editor."""
        if not barber_id:
            self.edit_services = []
            return
        rows = (await client.get(f"/barbers/{barber_id}/services/all")).json()
        self.edit_services = [
            Service(
                id=r["id"],
                name=r["name"],
                duration_minutes=r["duration_minutes"],
                is_active=r["is_active"],
            )
            for r in rows
        ]

    async def _load_schedule(self, client: httpx.AsyncClient, barber_id: int):
        if not barber_id:
            self.schedule = []
            return
        rows = (await client.get(f"/barbers/{barber_id}/appointments")).json()
        self.schedule = [
            ScheduleGroup(
                iso=iso,
                label=label,
                appts=[
                    ScheduledAppt(
                        id=r["id"],
                        time=r["start_at"][11:16],
                        customer_name=r["customer_name"],
                        customer_email=r["customer_email"],
                        customer_phone=r.get("customer_phone") or "",
                        service_id=r.get("service_id") or 0,
                        service_name=r.get("service_name") or "",
                        duration=r.get("duration_minutes") or 30,
                        group_id=r.get("recurrence_group_id") or "",
                    )
                    for r in day_rows
                ],
            )
            for iso, label, day_rows in _by_day(rows)
        ]
        # Keep the selected day valid: prefer today if it has bookings, else the
        # first booked day. This also re-anchors after a cancel empties a day.
        booked = {g.iso for g in self.schedule}
        if self.selected_day not in booked:
            today = date.today().isoformat()
            self.selected_day = (
                today if today in booked else (self.schedule[0].iso if self.schedule else today)
            )

    async def _load_theme(self, client: httpx.AsyncClient):
        """Load the shop's saved colours and logo so the site paints in them."""
        # Clear any unsaved pending logo from a previous interaction.
        self._pending_logo_b64 = ""
        self._pending_logo_name = ""
        self._pending_logo_type = ""
        self.logo_msg = ""
        try:
            theme = (await client.get("/settings/theme")).json()
            self.brand = theme["brand"]
            self.background = theme["background"]
            self.headline = theme["headline"]
            self.logo_version = str(theme["logo_version"])
            _public_cache["brand"] = self.brand
            _public_cache["background"] = self.background
            _public_cache["headline"] = self.headline
            _public_cache["logo_version"] = self.logo_version
        except (httpx.HTTPError, KeyError):
            pass  # keep the compile-time defaults

    def set_brand(self, value: str):
        self.brand = value  # live preview; save_theme persists it shop-wide

    def set_background(self, value: str):
        self.background = value

    def set_headline(self, value: str):
        self.headline = value

    @rx.event
    async def save_theme(self):
        self.theme_msg = ""
        async with httpx.AsyncClient(base_url=API_URL, timeout=15, headers=self._auth()) as client:
            # Save colours and headline.
            resp = await client.put(
                "/settings/theme",
                json={
                    "brand": self.brand,
                    "background": self.background,
                    "headline": self.headline,
                },
            )
            if resp.status_code != 200:
                self.theme_msg = "Não foi possível guardar."
                yield State.clear_message_after("theme_msg", self.theme_msg)
                return
            # Update the shared cache immediately so the next visitor (even
            # before their own on_load fetch resolves) sees the new theme
            # right away, instead of the brief old-value flash described in
            # _load_theme's docstring.
            _public_cache["brand"] = self.brand
            _public_cache["background"] = self.background
            _public_cache["headline"] = self.headline

            # Upload logo if one was staged.
            if self._pending_logo_b64:
                logo_data = base64.b64decode(self._pending_logo_b64)
                logo_resp = await client.put(
                    "/settings/logo",
                    files={"file": (self._pending_logo_name, logo_data, self._pending_logo_type)},
                )
                if logo_resp.status_code == 200:
                    self.logo_version = str(logo_resp.json()["logo_version"])
                    _public_cache["logo_version"] = self.logo_version
                    self._pending_logo_b64 = ""
                    self._pending_logo_name = ""
                    self._pending_logo_type = ""
                    self.logo_msg = ""
                else:
                    self.theme_msg = "Cores guardadas, mas o logótipo falhou."
                    yield State.clear_message_after("theme_msg", self.theme_msg)
                    return

            self.theme_msg = "Alterações guardadas."
        yield State.clear_message_after("theme_msg", self.theme_msg)

    @rx.event
    async def upload_logo(self, files: list[rx.UploadFile]):
        """Stage a new logo locally — it's sent to the backend on save."""
        self.logo_msg = ""
        if not files:
            return
        upload = files[0]
        data = await upload.read()
        self._pending_logo_b64 = base64.b64encode(data).decode()
        self._pending_logo_name = upload.filename or "logo"
        self._pending_logo_type = getattr(upload, "content_type", None) or "image/png"
        self.logo_msg = "Imagem selecionada — guarde para aplicar."
        yield State.clear_message_after("logo_msg", self.logo_msg)

    async def _load_hours(self, client: httpx.AsyncClient, barber_id: int):
        """Load a chair's weekly hours into the 7-day editor (all days present)."""
        if not barber_id:
            self.hours = []
            return
        self.allow_recurring = next(
            (b.allow_recurring for b in self.barbers if b.id == barber_id), False
        )
        self.max_recurring_weeks = str(
            next((b.max_recurring_weeks for b in self.barbers if b.id == barber_id), 12)
        )
        await self._load_services_editor(client, barber_id)
        rows = (await client.get(f"/barbers/{barber_id}/working-hours")).json()
        by_wd = {r["weekday"]: r for r in rows}
        self.hours = [
            HoursRow(
                weekday=wd,
                label=label,
                open=wd in by_wd,
                start=(by_wd[wd]["start_time"][:5] if wd in by_wd else "09:00"),
                end=(by_wd[wd]["end_time"][:5] if wd in by_wd else "17:00"),
                break_start=((by_wd[wd].get("break_start") or "")[:5] if wd in by_wd else ""),
                break_end=((by_wd[wd].get("break_end") or "")[:5] if wd in by_wd else ""),
            )
            for wd, label in _WEEKDAYS
        ]

    async def _fetch_slots(self, client: httpx.AsyncClient):
        self.selected_slot = ""
        if not self.selected_date or not self.selected_service:
            self.slots = []
            return
        resp = await client.get(
            f"/barbers/{self.selected_barber}/availability",
            params={"date": self.selected_date, "service_id": self.selected_service},
        )
        times = resp.json() if resp.status_code == 200 else []
        self.slots = [Slot(value=t, label=t[11:16]) for t in times]

    # --- auth events -----------------------------------------------------
    @rx.event
    async def login(self):
        self.auth_error = ""
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            resp = await client.post(
                "/auth/token", data={"username": self.form_email, "password": self.form_password}
            )
            if resp.status_code != 200:
                self.auth_error = "Email ou palavra-passe incorretos."
                return
            self.token = resp.json()["access_token"]
        # Decode the fresh token's claims right here, so is_admin/barber_id
        # land in the *same* delta as token — otherwise this event ends with
        # only token changed, briefly rendering the customer shell (stale
        # is_admin/barber_id) before refresh() corrects it on its own,
        # separate delta a moment later. See state.py's _decode_access_token
        # and refresh() for the equivalent reload-time optimisation.
        claims = _decode_access_token(self.token)
        if claims is not None:
            self.is_admin = bool(claims.get("is_admin", False))
            self.barber_id = int(claims.get("barber_id", 0))
        self.form_password = ""
        return State.refresh

    @rx.event
    async def register(self):
        self.auth_error = ""
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            resp = await client.post(
                "/auth/register",
                json={
                    "email": self.form_email,
                    "full_name": self.form_name,
                    "password": self.form_password,
                },
            )
            if resp.status_code == 409:
                self.auth_error = "Esse email já está registado."
                return
            if resp.status_code >= 400:
                self.auth_error = "Verifique os seus dados e tente novamente."
                return
        return State.login  # sign the new user straight in

    @rx.event
    def logout(self):
        self.token = ""
        self.user_name = ""
        self.is_admin = False
        self.is_verified = False
        self.barber_id = 0
        self.my_appointments = []
        self.schedule = []
        self.recurring_series = []
        self.selected_day = ""
        self.hours = []
        self.hours_msg = ""
        self.booking_msg = ""
        self.needs_verify = False
        self.manual_name = ""
        self.manual_email = ""
        self.manual_msg = ""
        self.cal_month = ""
        self.selected_date = ""
        self.selected_slot = ""
        self.slots = []
        self.perpetual = False
        self.profile_name = ""
        self.profile_phone = ""
        self.profile_msg = ""
        self.pw_current = ""
        self.pw_new = ""
        self.pw_msg = ""
        self.auth_mode = "login"

    @rx.event
    def set_auth_mode(self, mode: str):
        self.auth_mode = mode
        self.auth_error = ""

    @rx.event
    async def forgot_password(self):
        """Ask the backend to email a reset link (always succeeds from the UI)."""
        self.auth_error = ""
        if not self.form_email.strip():
            self.auth_error = "Introduza o seu email."
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            await client.post("/auth/forgot-password", json={"email": self.form_email})
        self.auth_error = "Se o email existir, receberá instruções para repor a palavra-passe."

    @rx.event
    def load_reset_token(self):
        """Read the token from the URL query string on page load."""
        self.reset_token = self.router.page.params.get("token", "")
        self.reset_msg = ""
        self.reset_done = False
        self.reset_new_password = ""

    @rx.event
    def set_reset_new_password(self, value: str):
        self.reset_new_password = value

    @rx.event
    async def submit_reset(self):
        """Send the new password + token to the backend."""
        self.reset_msg = ""
        if len(self.reset_new_password) < 8:
            self.reset_msg = "A palavra-passe deve ter pelo menos 8 caracteres."
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            resp = await client.post(
                "/auth/reset-password",
                json={"token": self.reset_token, "new_password": self.reset_new_password},
            )
        if resp.status_code == 200:
            self.reset_msg = "Palavra-passe alterada com sucesso. Pode iniciar sessão."
            self.reset_done = True
        else:
            self.reset_msg = "Link inválido ou expirado. Peça um novo."

    @rx.event
    async def load_verify_token(self):
        """Read the token from the URL query string and verify it right away.

        Calls the backend server-side (API_URL, container-internal) so the
        booking API never needs to be reachable from the browser for this —
        only this page (already public) does.
        """
        token = self.router.page.params.get("token", "")
        self.verify_msg = ""
        self.verify_done = False
        if not token:
            self.verify_msg = "Link inválido."
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            resp = await client.get("/auth/verify", params={"token": token})
        if resp.status_code == 200:
            self.verify_msg = "Email verificado com sucesso. Pode iniciar sessão."
            self.verify_done = True
        else:
            self.verify_msg = "Link inválido ou expirado. Peça um novo email de verificação."

    @rx.event
    async def change_password(self):
        """Change the current user's password (must know the old one)."""
        self.pw_msg = ""
        if len(self.pw_new) < 8:
            self.pw_msg = "A nova palavra-passe deve ter pelo menos 8 caracteres."
            yield State.clear_message_after("pw_msg", self.pw_msg)
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.put(
                "/auth/me/password",
                json={"current_password": self.pw_current, "new_password": self.pw_new},
            )
        if resp.status_code == 200:
            self.pw_msg = "Palavra-passe alterada."
            self.pw_current = ""
            self.pw_new = ""
        elif resp.status_code == 403:
            self.pw_msg = "Palavra-passe atual incorreta."
        else:
            self.pw_msg = "Não foi possível alterar. Tente novamente."
        yield State.clear_message_after("pw_msg", self.pw_msg)

    @rx.event
    def set_form_name(self, value: str):
        self.form_name = value

    @rx.event
    def set_form_email(self, value: str):
        self.form_email = value

    @rx.event
    def set_form_password(self, value: str):
        self.form_password = value

    @rx.event
    def set_pw_current(self, value: str):
        self.pw_current = value

    @rx.event
    def set_pw_new(self, value: str):
        self.pw_new = value

    @rx.event
    def set_manual_name(self, value: str):
        self.manual_name = value

    @rx.event
    def set_manual_email(self, value: str):
        self.manual_email = value

    # --- profile events --------------------------------------------------
    @rx.event
    def set_profile_name(self, value: str):
        self.profile_name = value

    @rx.event
    def set_profile_phone(self, value: str):
        self.profile_phone = value

    @rx.event
    async def save_profile(self):
        """Save the user's edited name and phone."""
        self.profile_msg = ""
        if self.profile_name.strip() == "":
            self.profile_msg = "O nome não pode ficar em branco."
            yield State.clear_message_after("profile_msg", self.profile_msg)
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.patch(
                "/auth/me",
                json={"full_name": self.profile_name, "phone": self.profile_phone},
            )
            if resp.status_code == 200:
                user = resp.json()
                self.user_name = user["full_name"]
                self.profile_name = user["full_name"]
                self.profile_phone = user["phone"] or ""
                self.profile_msg = "Dados atualizados."
            else:
                self.profile_msg = "Não foi possível guardar. Tente novamente."
        yield State.clear_message_after("profile_msg", self.profile_msg)

    # --- booking events --------------------------------------------------
    @rx.event
    async def select_barber(self, barber_id: int):
        self.selected_barber = barber_id
        self.loading_slots = True
        yield
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            await self._load_services(client, barber_id)
            await self._fetch_slots(client)
        self.loading_slots = False

    @rx.event
    async def select_service(self, value: str):
        self.selected_service = int(value)
        self.loading_slots = True
        yield
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            await self._fetch_slots(client)
        self.loading_slots = False

    @rx.event
    def set_repeat_weeks(self, value: str):
        self.repeat_weeks = value

    @rx.event
    def set_perpetual(self, value: bool):
        self.perpetual = value

    @rx.event
    async def select_date(self, iso: str):
        self.selected_date = iso
        self.loading_slots = True
        yield
        async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
            await self._fetch_slots(client)
        self.loading_slots = False

    @rx.event
    def select_slot(self, value: str):
        self.selected_slot = value

    def _shift_month(self, months: int):
        anchor = self._cal_anchor()
        total = anchor.month - 1 + months
        self.cal_month = date(anchor.year + total // 12, total % 12 + 1, 1).isoformat()

    @rx.event
    def cal_prev(self):
        if self.can_cal_prev:
            self._shift_month(-1)

    @rx.event
    def cal_next(self):
        self._shift_month(1)

    @rx.event
    async def book(self):
        self.booking_msg = ""
        self.booking_msg_color = "blue"
        self.needs_verify = False
        if not self.selected_slot or not self.selected_service:
            return
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.post(
                "/appointments",
                json={
                    "barber_id": self.selected_barber,
                    "service_id": self.selected_service,
                    "start_at": self.selected_slot,
                    "repeat_weeks": int(self.repeat_weeks),
                    "perpetual": self.perpetual,
                },
            )
            if resp.status_code == 201:
                skipped = len(resp.json().get("skipped", []))
                self.booking_msg = (
                    "Marcado! Está na sua lista abaixo."
                    if not skipped
                    else f"Marcado! {skipped} semana(s) já estavam ocupadas e foram ignoradas."
                )
                self.perpetual = False
                await self._fetch_slots(client)
                await self._load_my_appointments(client)
                await self._load_recurring_series(client)
            elif resp.status_code == 403:
                self.needs_verify = True
            elif resp.status_code == 409 and _error_code(resp) == STANDING_SLOT_CONFLICT:
                self.booking_msg = "Já tem um horário fixo nesse dia da semana e hora."
            elif resp.status_code == 409:
                self.booking_msg = "Esse horário acabou de ser ocupado — escolha outro."
                await self._fetch_slots(client)
            else:
                self.booking_msg = "Não foi possível marcar. Tente novamente."
        yield State.clear_message_after("booking_msg", self.booking_msg)

    @rx.event
    async def cancel_appointment(self, appt_id: int):
        """Cancel a single booking (customer-facing)."""
        self.booking_msg_color = "tomato"
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.delete(f"/appointments/{appt_id}")
            if resp.status_code == 403:
                self.booking_msg = "Demasiado tarde para cancelar online — ligue para a barbearia."
            elif resp.status_code == 204:
                self.booking_msg = "Marcação cancelada."
            else:
                self.booking_msg = "Não foi possível cancelar. Tente novamente."
            await self._load_my_appointments(client)
            await self._fetch_slots(client)
        yield State.clear_message_after("booking_msg", self.booking_msg)

    @rx.event
    async def resend_verification(self):
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            await client.post("/auth/resend-verification")
        self.needs_verify = False
        self.booking_msg = "Email de verificação enviado — verifique a caixa de entrada."

    @rx.event
    async def view_barber_schedule(self, barber_id: int):
        self.admin_barber = barber_id
        self.selected_barber = barber_id  # the manual-booking card targets this chair
        self.selected_date = ""
        self.selected_slot = ""
        self.slots = []
        self.manual_msg = ""
        self.hours_msg = ""
        self.selected_day = ""  # re-anchor the agenda to a booked day on load
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            await self._load_schedule(client, barber_id)
            await self._load_hours(client, barber_id)
            await self._load_services(client, barber_id)

    @rx.event
    async def cancel_schedule_appointment(self, appt_id: int):
        """Staff cancel a booking from the agenda; the customer is emailed."""
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            await client.delete(f"/appointments/{appt_id}")
            await self._load_schedule(client, self.selected_barber)
            await self._fetch_slots(client)

    # --- working-hours events --------------------------------------------
    @rx.event
    def toggle_hours_day(self, weekday: str, value: bool):
        self.hours = [
            dataclasses.replace(r, open=value) if r.weekday == weekday else r
            for r in self.hours
        ]

    @rx.event
    def set_hours_time(self, weekday: str, field: str, value: str):
        self.hours = [
            dataclasses.replace(r, **{field: value}) if r.weekday == weekday else r
            for r in self.hours
        ]

    @rx.event
    async def save_hours(self):
        """Save the open days as the chair's weekly working hours."""
        self.hours_msg = ""
        payload = []
        for r in self.hours:
            if not r.open:
                continue
            if r.start >= r.end:
                self.hours_msg = f"{r.label}: o início tem de ser antes do fim."
                yield State.clear_message_after("hours_msg", self.hours_msg)
                return
            item = {"weekday": r.weekday, "start_time": r.start, "end_time": r.end}
            if bool(r.break_start) != bool(r.break_end):
                self.hours_msg = f"{r.label}: indique o início e o fim da pausa."
                yield State.clear_message_after("hours_msg", self.hours_msg)
                return
            if r.break_start and r.break_end:
                item["break_start"] = r.break_start
                item["break_end"] = r.break_end
            payload.append(item)
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.put(
                f"/barbers/{self.selected_barber}/working-hours", json=payload
            )
            if resp.status_code == 200:
                self.hours_msg = "Horário atualizado."
                await self._load_hours(client, self.selected_barber)
                await self._fetch_slots(client)
            elif resp.status_code == 422:
                self.hours_msg = "A pausa tem de ficar dentro do horário de trabalho."
            else:
                self.hours_msg = "Não foi possível guardar. Tente novamente."
        yield State.clear_message_after("hours_msg", self.hours_msg)

    # --- services editor (barber configures the chair's service menu) -----
    # Changes are kept local until the user clicks "Guardar", then saved in bulk.

    def set_new_service_name(self, value: str):
        self.new_service_name = value

    def set_new_service_minutes(self, value: str):
        self.new_service_minutes = value

    def add_service(self):
        """Add a new service to the local draft."""
        self.service_msg = ""
        name = self.new_service_name.strip()
        if not name:
            self.service_msg = "Indique o nome do serviço."
            yield State.clear_message_after("service_msg", self.service_msg)
            return
        self.edit_services.append(
            Service(id=self._next_local_id, name=name, duration_minutes=int(self.new_service_minutes))
        )
        self._next_local_id -= 1
        self.new_service_name = ""

    def rename_service(self, service_id: int, value: str):
        name = value.strip()
        if not name:
            return
        for svc in self.edit_services:
            if svc.id == service_id:
                svc.name = name
                break

    def set_service_minutes(self, service_id: int, value: str):
        for svc in self.edit_services:
            if svc.id == service_id:
                svc.duration_minutes = int(value)
                break

    def toggle_service_active(self, service_id: int, value: bool):
        for svc in self.edit_services:
            if svc.id == service_id:
                svc.is_active = value
                break

    def delete_service(self, service_id: int):
        """Remove a service from the local draft."""
        self.edit_services = [s for s in self.edit_services if s.id != service_id]

    @rx.event
    async def save_services(self):
        """Persist the full service menu to the backend in one call."""
        self.service_msg = ""
        payload = [
            {
                "id": s.id if s.id > 0 else None,
                "name": s.name,
                "duration_minutes": s.duration_minutes,
                "is_active": s.is_active,
            }
            for s in self.edit_services
        ]
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.put(
                f"/barbers/{self.selected_barber}/services", json=payload
            )
            if resp.status_code == 200:
                self.service_msg = "Serviços guardados."
                await self._load_services_editor(client, self.selected_barber)
                await self._load_services(client, self.selected_barber)
            else:
                self.service_msg = "Não foi possível guardar os serviços."
        yield State.clear_message_after("service_msg", self.service_msg)

    # --- recurrence policy (owner lets customers repeat weekly) -----------
    @rx.event
    async def toggle_allow_recurring(self, value: bool):
        self.recurring_msg = ""
        self.allow_recurring = value
        await self._patch_barber({"allow_recurring": value}, "allow_recurring", value)
        yield State.clear_message_after("recurring_msg", self.recurring_msg)

    @rx.event
    async def set_max_recurring_weeks(self, value: str):
        self.recurring_msg = ""
        self.max_recurring_weeks = value
        await self._patch_barber(
            {"max_recurring_weeks": int(value)}, "max_recurring_weeks", int(value)
        )
        yield State.clear_message_after("recurring_msg", self.recurring_msg)

    async def _patch_barber(self, body: dict, field: str, cached):
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.patch(f"/barbers/{self.selected_barber}", json=body)
            if resp.status_code == 200:
                self.recurring_msg = "Guardado."
                for b in self.barbers:
                    if b.id == self.selected_barber:
                        setattr(b, field, cached)
            else:
                self.recurring_msg = "Não foi possível guardar. Tente novamente."

    # --- switch a booking's service (staff, from the agenda) --------------
    @rx.event
    async def switch_service(self, appt_id: int, value: str):
        """Change an existing booking's service, freeing or using agenda time."""
        self.hours_msg = ""
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.patch(
                f"/appointments/{appt_id}", json={"service_id": int(value)}
            )
            if resp.status_code == 409:
                self.hours_msg = "O novo serviço não cabe nesse horário — liberte espaço primeiro."
            await self._load_schedule(client, self.selected_barber)
            await self._fetch_slots(client)
        yield State.clear_message_after("hours_msg", self.hours_msg)

    @rx.event
    async def cancel_series(self, group_id: str):
        """Cancel every upcoming booking in a weekly series (customer-facing).

        Only reloads the customer's own list — reloading the barber agenda
        here would 403 for a plain customer (selected_barber may hold some
        other barber browsed earlier on the public page) and crash the UI.
        """
        self.booking_msg_color = "tomato"
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.delete(f"/appointments/series/{group_id}")
            self.booking_msg = (
                "Série cancelada." if resp.status_code == 204 else "Não foi possível cancelar a série."
            )
            await self._load_my_appointments(client)
            await self._load_recurring_series(client)
            await self._fetch_slots(client)
        yield State.clear_message_after("booking_msg", self.booking_msg)

    @rx.event
    async def cancel_recurring_series(self, series_id: str):
        """End a "Horário Fixo" for good — used by the standing-bookings card.

        Unlike cancel_series (customer-only), this card is shown to every
        role, so it must reload whichever list actually belongs to the
        current viewer: the barber/admin agenda for staff, or the
        customer's own appointment list otherwise.
        """
        self.booking_msg_color = "tomato"
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.delete(f"/appointments/series/{series_id}")
            self.booking_msg = (
                "Horário fixo cancelado."
                if resp.status_code == 204
                else "Não foi possível cancelar."
            )
            if self.is_admin or self.barber_id:
                await self._load_schedule(client, self.selected_barber)
            else:
                await self._load_my_appointments(client)
            await self._load_recurring_series(client)
            await self._fetch_slots(client)
        yield State.clear_message_after("booking_msg", self.booking_msg)

    @rx.event
    async def book_manual(self):
        """Book the chosen slot for a walk-in (name) or an existing account (email)."""
        self.manual_msg = ""
        if not self.can_book_manual:
            self.manual_msg = "Indique o nome (ou email) e escolha um horário."
            yield State.clear_message_after("manual_msg", self.manual_msg)
            return
        payload = {
            "barber_id": self.selected_barber,
            "service_id": self.selected_service,
            "start_at": self.selected_slot,
            "customer_name": self.manual_name,
            "customer_email": self.manual_email,
            "repeat_weeks": int(self.repeat_weeks),
            "perpetual": self.perpetual,
        }
        async with httpx.AsyncClient(base_url=API_URL, timeout=5, headers=self._auth()) as client:
            resp = await client.post("/appointments/manual", json=payload)
            if resp.status_code == 201:
                skipped = len(resp.json().get("skipped", []))
                self.manual_msg = (
                    "Marcado para o cliente."
                    if not skipped
                    else f"Marcado. {skipped} semana(s) já estavam ocupadas."
                )
                self.manual_name = ""
                self.manual_email = ""
                self.perpetual = False
                await self._fetch_slots(client)
                await self._load_schedule(client, self.selected_barber)
                await self._load_recurring_series(client)
            elif resp.status_code == 404:
                self.manual_msg = "Não existe conta com esse email."
            elif resp.status_code == 409 and _error_code(resp) == STANDING_SLOT_CONFLICT:
                self.manual_msg = "Este cliente já tem um horário fixo nesse dia e hora."
            elif resp.status_code == 409:
                self.manual_msg = "Esse horário já não está disponível."
            else:
                self.manual_msg = "Não foi possível marcar. Verifique os dados."
        yield State.clear_message_after("manual_msg", self.manual_msg)

