"""The four things a visitor can see, one function each.

- ``auth_view``      — signed out: sign in or create an account
- ``customer_view``  — book a cut and manage your own appointments
- ``barber_view``    — a barber's own day, who's booked in
- ``admin_view``     — the owner: any barber's book, plus the admin console
"""

from typing import Any, cast

import reflex as rx

from shop.state import (
    Appt,
    ApptGroup,
    Barber,
    CalCell,
    Day,
    DayTab,
    HoursRow,
    ScheduledAppt,
    Service,
    Slot,
    State,
)
from shop.ui import (
    BORDER,
    BRAND,
    BRAND_CONTRAST,
    BRAND_TEXT,
    CARD,
    INK,
    MUTED,
    SUBTLE,
    card,
    empty,
    muted,
    panel_title,
    row,
    step,
)

# --- booking pieces (shared by the customer view) ------------------------


def barber_card(barber: Barber) -> rx.Component:
    active = State.selected_barber == barber.id
    return rx.hstack(
        rx.icon("scissors", size=18, color=BRAND_TEXT),
        rx.text(barber.name, weight="bold", color=INK),
        on_click=State.select_barber(barber.id),
        cursor="pointer",
        padding="0.7rem 1rem",
        border_radius="14px",
        background=SUBTLE,
        border=rx.cond(active, f"2px solid {BRAND}", "2px solid transparent"),
        align="center",
        spacing="2",
        transition="border-color 0.15s ease",
    )


def day_chip(day: Day) -> rx.Component:
    active = State.selected_date == day.iso
    return rx.vstack(
        rx.text(day.dow, size="1", weight="medium"),
        rx.text(day.dom, size="4", weight="bold"),
        on_click=State.select_date(day.iso),
        cursor="pointer",
        padding="0.55rem 0.8rem",
        border_radius="14px",
        min_width="3.2rem",
        flex_shrink="0",
        align="center",
        spacing="0",
        background=rx.cond(active, BRAND, SUBTLE),
        color=rx.cond(active, BRAND_CONTRAST, INK),
        transition="background 0.15s ease",
    )


def slot_pill(slot: Slot) -> rx.Component:
    active = State.selected_slot == slot.value
    return rx.button(
        slot.label,
        on_click=State.select_slot(slot.value),
        variant=rx.cond(active, "solid", "soft"),
        size="3",
        border_radius="12px",
    )


def service_pill(service: Service) -> rx.Component:
    active = State.selected_service == service.id
    return rx.button(
        rx.hstack(
            rx.text(service.name, weight="bold"),
            rx.text(f"{service.duration_minutes} min", size="1", opacity="0.8"),
            align="center",
            spacing="2",
        ),
        on_click=State.select_service(service.id.to_string()),
        variant=rx.cond(active, "solid", "soft"),
        size="3",
        border_radius="12px",
    )


def service_area() -> rx.Component:
    return rx.cond(
        State.services,
        rx.flex(rx.foreach(State.services, service_pill), wrap="wrap", gap="2"),
        muted("Este barbeiro ainda não definiu serviços."),
    )


def recurrence_controls() -> rx.Component:
    """The 'repeat weekly for N weeks' row — shared by customer and staff booking."""
    return rx.hstack(
        rx.icon("repeat", size=16, color=BRAND_TEXT),
        rx.text("Repetir semanalmente", size="2", color=INK),
        rx.select(
            State.repeat_options,
            value=State.repeat_weeks,
            on_change=State.set_repeat_weeks,
            size="2",
        ),
        rx.text("semana(s)", size="2", color=INK),
        align="center",
        spacing="2",
        wrap="wrap",
    )


def recurrence_selector() -> rx.Component:
    """Let the customer repeat the booking weekly, if the barber allows it."""
    return rx.cond(State.barber_allows_recurring, recurrence_controls())


def slots_area() -> rx.Component:
    return rx.cond(
        State.selected_date == "",
        muted("Escolha um dia para ver os horários disponíveis."),
        rx.cond(
            State.loading_slots,
            rx.spinner(size="3", color=BRAND),
            rx.cond(
                State.slots,
                rx.flex(rx.foreach(State.slots, slot_pill), wrap="wrap", gap="2"),
                muted("Sem horários nesse dia — experimente outro."),
            ),
        ),
    )


def booking_card() -> rx.Component:
    return card(
        rx.vstack(
            step(
                "1",
                "Escolha o seu barbeiro",
                rx.flex(rx.foreach(State.barbers, barber_card), wrap="wrap", gap="2"),
            ),
            step("2", "Escolha o serviço", service_area()),
            step(
                "3",
                "Escolha um dia",
                rx.hstack(
                    rx.foreach(State.days, day_chip),
                    overflow_x="auto",
                    width="100%",
                    padding_bottom="0.4rem",
                    spacing="2",
                ),
            ),
            step("4", "Escolha uma hora", slots_area()),
            recurrence_selector(),
            rx.button(
                rx.hstack(rx.text("Marcar"), rx.icon("arrow-right", size=18), align="center"),
                on_click=State.book,
                disabled=~State.can_book,
                size="4",
                width="100%",
                border_radius="14px",
            ),
            spacing="6",
            width="100%",
        )
    )


# --- feedback banners ----------------------------------------------------


def verify_banner() -> rx.Component:
    """Shown to a customer who hasn't confirmed their email yet."""
    return rx.cond(
        ~State.is_verified,
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon("mail-warning", size=20, color=rx.color("amber", 11)),
                    rx.text("Confirme o seu email para começar a marcar", weight="bold", color=INK),
                    align="center",
                    spacing="2",
                ),
                muted("Enviámos-lhe um link. Não recebeu? Enviamos outro."),
                rx.hstack(
                    rx.button(
                        "Reenviar email",
                        on_click=State.resend_verification,
                        variant="soft",
                        color_scheme="amber",
                        size="2",
                    ),
                    rx.cond(
                        State.mail_inbox_url != "",
                        rx.link(
                            rx.button(
                                rx.hstack(
                                    rx.icon("inbox", size=15),
                                    rx.text("Abrir a caixa de entrada"),
                                    align="center",
                                    spacing="2",
                                ),
                                variant="soft",
                                color_scheme="amber",
                                size="2",
                            ),
                            href=State.mail_inbox_url,
                            is_external=True,
                        ),
                    ),
                    spacing="2",
                ),
                spacing="3",
                align="start",
            ),
            background=rx.color("amber", 2),
            border=f"1px solid {rx.color('amber', 6)}",
        ),
    )


def booking_message() -> rx.Component:
    return rx.cond(
        State.booking_msg != "",
        rx.callout(State.booking_msg, icon="info", width="100%"),
    )


def verify_prompt() -> rx.Component:
    """A one-off nudge after a booking attempt was blocked for verification."""
    return rx.cond(
        State.needs_verify,
        rx.callout(
            "Confirme primeiro o seu email — verifique a caixa de entrada.",
            icon="mail-warning",
            color_scheme="amber",
            width="100%",
        ),
    )


# --- appointment lists ---------------------------------------------------


def day_header(label: str | rx.Var[str]) -> rx.Component:
    """A small uppercase heading that separates one day from the next."""
    return rx.text(
        label,
        size="1",
        weight="bold",
        color=BRAND_TEXT,
        text_transform="uppercase",
        letter_spacing="0.06em",
        padding_top="0.9rem",
    )


def my_appointment_row(appt: Appt) -> rx.Component:
    return row(
        rx.hstack(
            rx.icon("calendar-check", size=18, color=BRAND),
            rx.vstack(
                rx.hstack(
                    rx.text(appt.time, weight="bold", color=INK, size="2"),
                    rx.cond(
                        appt.group_id != "",
                        rx.badge(
                            rx.icon("repeat", size=12),
                            color_scheme="grass",
                            variant="soft",
                            radius="full",
                        ),
                    ),
                    align="center",
                    spacing="2",
                ),
                muted(f"com {appt.barber_name}", size="1"),
                spacing="0",
                align="start",
            ),
            align="center",
            spacing="3",
        ),
        rx.hstack(
            rx.cond(
                appt.group_id != "",
                rx.button(
                    "Cancelar série",
                    on_click=State.cancel_series(appt.group_id),
                    variant="soft",
                    color_scheme="tomato",
                    size="1",
                ),
            ),
            rx.button(
                "Cancelar",
                on_click=State.cancel_appointment(appt.id),
                variant="soft",
                color_scheme="tomato",
                size="1",
            ),
            spacing="2",
        ),
    )


def service_switcher(appt: ScheduledAppt) -> rx.Component:
    """A dropdown to change this booking's service, freeing or using agenda time."""
    return rx.select.root(
        rx.select.trigger(variant="soft", radius="large"),
        rx.select.content(
            rx.foreach(
                State.services,
                lambda s: rx.select.item(
                    f"{s.name} · {s.duration_minutes} min", value=s.id.to_string()
                ),
            ),
        ),
        value=appt.service_id.to_string(),
        on_change=lambda v: State.switch_service(appt.id, v),
        size="1",
    )


def schedule_row(appt: ScheduledAppt) -> rx.Component:
    return row(
        rx.hstack(
            rx.icon("clock", size=18, color=BRAND),
            rx.vstack(
                rx.hstack(
                    rx.text(appt.time, weight="bold", color=INK, size="2"),
                    rx.cond(
                        appt.group_id != "",
                        rx.badge(
                            rx.icon("repeat", size=12),
                            color_scheme="grass",
                            variant="soft",
                            radius="full",
                        ),
                    ),
                    align="center",
                    spacing="2",
                ),
                muted(appt.customer_name, size="1"),
                rx.cond(appt.service_name != "", muted(appt.service_name, size="1")),
                spacing="0",
                align="start",
            ),
            align="center",
            spacing="3",
        ),
        rx.hstack(
            service_switcher(appt),
            rx.cond(
                appt.customer_email != "",
                muted(appt.customer_email, size="1"),
                rx.badge("Sem conta", color_scheme="gray", variant="soft", radius="full"),
            ),
            rx.button(
                "Cancelar",
                on_click=State.cancel_schedule_appointment(appt.id),
                variant="soft",
                color_scheme="tomato",
                size="1",
            ),
            align="center",
            spacing="2",
            wrap="wrap",
        ),
    )


def my_appointment_group(group: ApptGroup) -> rx.Component:
    return rx.vstack(
        day_header(group.label),
        rx.foreach(group.appts, my_appointment_row),
        spacing="0",
        width="100%",
        align="start",
    )


def schedule_day_chip(tab: DayTab) -> rx.Component:
    """One day in the barber's week strip, with a count badge when it's booked."""
    active = State.selected_day == tab.iso
    return rx.vstack(
        rx.text(tab.dow, size="1", weight="medium"),
        rx.text(tab.dom, size="4", weight="bold"),
        rx.cond(
            tab.count > 0,
            rx.center(
                rx.text(tab.count, size="1", weight="bold"),
                background=rx.cond(active, BRAND_CONTRAST, BRAND),
                color=rx.cond(active, BRAND_TEXT, BRAND_CONTRAST),
                border_radius="999px",
                min_width="1.25rem",
                height="1.25rem",
                padding_x="0.3rem",
            ),
            rx.box(height="1.25rem"),  # keep chips the same height when empty
        ),
        on_click=State.select_schedule_day(tab.iso),
        cursor="pointer",
        padding="0.5rem 0.7rem",
        border_radius="14px",
        min_width="3.4rem",
        flex_shrink="0",
        align="center",
        spacing="1",
        background=rx.cond(active, BRAND, SUBTLE),
        color=rx.cond(active, BRAND_CONTRAST, INK),
        transition="background 0.15s ease",
    )


def selected_day_agenda() -> rx.Component:
    """The appointments for the day chosen in the week strip — one day at a time."""
    return rx.vstack(
        day_header(State.selected_day_label),
        rx.cond(
            State.selected_day_appts,
            rx.vstack(
                rx.foreach(State.selected_day_appts, schedule_row),
                spacing="0",
                width="100%",
            ),
            empty("Dia livre — nada marcado."),
        ),
        spacing="0",
        width="100%",
        align="start",
    )


def cal_cell(cell: CalCell) -> rx.Component:
    """One day in the month grid — or an empty square before the 1st."""
    selected = State.selected_date == cell.iso
    return rx.cond(
        cell.iso == "",
        rx.box(),
        rx.button(
            cell.dom,
            on_click=State.select_date(cell.iso),
            disabled=cell.disabled,
            variant=rx.cond(selected, "solid", "soft"),
            size="2",
            width="100%",
            aspect_ratio="1",
            padding="0",
            border_radius="10px",
        ),
    )


def calendar_picker() -> rx.Component:
    """A compact, on-brand month calendar for picking a day to book."""
    return rx.vstack(
        rx.hstack(
            rx.icon_button(
                rx.icon("chevron-left", size=18),
                on_click=State.cal_prev,
                disabled=~State.can_cal_prev,
                variant="ghost",
                aria_label="Mês anterior",
            ),
            rx.spacer(),
            rx.text(State.cal_title, weight="bold", color=INK, size="3"),
            rx.spacer(),
            rx.icon_button(
                rx.icon("chevron-right", size=18),
                on_click=State.cal_next,
                variant="ghost",
                aria_label="Mês seguinte",
            ),
            width="100%",
            align="center",
        ),
        rx.grid(
            rx.foreach(
                State.cal_weekdays,
                lambda w: rx.center(
                    rx.text(w, size="1", weight="medium", color=BRAND_TEXT)
                ),
            ),
            columns="7",
            width="100%",
            gap="1",
        ),
        rx.grid(
            rx.foreach(State.cal_cells, cal_cell),
            columns="7",
            width="100%",
            gap="1",
        ),
        spacing="3",
        width="100%",
    )


def manual_booking_card() -> rx.Component:
    """The barber/owner books a slot for someone else — a walk-in or an account."""
    return card(
        rx.vstack(
            panel_title("Marcar para um cliente", "Reserve um horário em nome de alguém"),
            rx.input(
                placeholder="Nome do cliente",
                value=State.manual_name,
                on_change=State.set_manual_name,
                size="3",
                width="100%",
            ),
            rx.input(
                placeholder="Email da conta (opcional)",
                type="email",
                value=State.manual_email,
                on_change=State.set_manual_email,
                size="3",
                width="100%",
            ),
            muted("Sem conta? Basta o nome. Com conta? Indique o email para a associar."),
            rx.vstack(
                muted("Serviço", size="1"),
                service_area(),
                spacing="2",
                align="start",
                width="100%",
            ),
            rx.vstack(
                muted("Escolha o dia", size="1"),
                calendar_picker(),
                spacing="2",
                align="start",
                width="100%",
            ),
            slots_area(),
            recurrence_controls(),
            rx.cond(
                State.manual_msg != "",
                rx.callout(State.manual_msg, icon="info", width="100%"),
            ),
            rx.button(
                rx.hstack(rx.text("Marcar para o cliente"), rx.icon("user-plus", size=18), align="center"),
                on_click=State.book_manual,
                disabled=~State.can_book_manual,
                size="3",
                width="100%",
                border_radius="14px",
            ),
            spacing="4",
            width="100%",
        )
    )


# --- working hours (barber / admin edits a chair's weekly schedule) ------


def _time_field(label: str, value, on_change) -> rx.Component:
    return rx.vstack(
        muted(label, size="1"),
        rx.input(type="time", value=value, on_change=on_change, size="2", width="100%"),
        spacing="1",
        align="start",
        width="100%",
    )


def hours_row(row: HoursRow) -> rx.Component:
    """One weekday: an open/closed switch and, when open, its times."""
    return rx.vstack(
        rx.hstack(
            rx.text(row.label, weight="bold", color=INK, size="2"),
            rx.spacer(),
            rx.cond(row.open, muted("Aberto", size="1"), muted("Fechado", size="1")),
            rx.switch(
                checked=row.open,
                on_change=lambda v: State.toggle_hours_day(row.weekday, v),
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.cond(
            row.open,
            rx.vstack(
                rx.hstack(
                    _time_field(
                        "Início", row.start,
                        lambda v: State.set_hours_time(row.weekday, "start", v),
                    ),
                    _time_field(
                        "Fim", row.end,
                        lambda v: State.set_hours_time(row.weekday, "end", v),
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.hstack(
                    _time_field(
                        "Pausa (início)", row.break_start,
                        lambda v: State.set_hours_time(row.weekday, "break_start", v),
                    ),
                    _time_field(
                        "Pausa (fim)", row.break_end,
                        lambda v: State.set_hours_time(row.weekday, "break_end", v),
                    ),
                    spacing="3",
                    width="100%",
                ),
                spacing="2",
                width="100%",
                padding_top="0.5rem",
            ),
        ),
        spacing="1",
        width="100%",
        padding_y="0.8rem",
        border_top=f"1px solid {BORDER}",
        align="start",
    )


def working_hours_card() -> rx.Component:
    """The barber (or an admin) sets which days and hours a chair works."""
    return card(
        rx.vstack(
            panel_title("Horário de trabalho", "Defina os dias e as horas em que atende"),
            rx.vstack(rx.foreach(State.hours, hours_row), spacing="0", width="100%"),
            rx.cond(
                State.hours_msg != "",
                rx.callout(State.hours_msg, icon="info", width="100%"),
            ),
            rx.button(
                rx.hstack(rx.text("Guardar horário"), rx.icon("check", size=18), align="center"),
                on_click=State.save_hours,
                size="3",
                width="100%",
                border_radius="14px",
            ),
            spacing="4",
            width="100%",
        )
    )


# --- services + recurrence (barber configures the chair's service menu) ---


def service_editor_row(service: Service) -> rx.Component:
    """One service: rename it, retime it, activate/deactivate, or remove it."""
    return rx.hstack(
        rx.input(
            default_value=service.name,
            on_blur=lambda v: State.rename_service(service.id, v),
            size="2",
            flex="1",
            min_width="7rem",
        ),
        rx.select(
            State.duration_options,
            value=service.duration_minutes.to_string(),
            on_change=lambda v: State.set_service_minutes(service.id, v),
            size="2",
        ),
        rx.switch(
            checked=service.is_active,
            on_change=lambda v: State.toggle_service_active(service.id, v),
        ),
        rx.icon_button(
            rx.icon("trash-2", size=15),
            on_click=State.delete_service(service.id),
            variant="soft",
            color_scheme="tomato",
            size="2",
        ),
        width="100%",
        align="center",
        spacing="2",
        wrap="wrap",
        padding_y="0.5rem",
        border_top=f"1px solid {BORDER}",
    )


def services_card() -> rx.Component:
    """The barber curates the service menu and the weekly-recurrence policy."""
    return card(
        rx.vstack(
            panel_title("Serviços", "Defina os serviços e a duração de cada um"),
            rx.vstack(rx.foreach(State.edit_services, service_editor_row), spacing="0", width="100%"),
            rx.hstack(
                rx.input(
                    placeholder="Novo serviço",
                    value=State.new_service_name,
                    on_change=State.set_new_service_name,
                    size="2",
                    flex="1",
                    min_width="7rem",
                ),
                rx.select(
                    State.duration_options,
                    value=State.new_service_minutes,
                    on_change=State.set_new_service_minutes,
                    size="2",
                ),
                rx.button(
                    rx.icon("plus", size=16),
                    on_click=State.add_service,
                    variant="soft",
                    size="2",
                ),
                width="100%",
                align="center",
                spacing="2",
                wrap="wrap",
            ),
            rx.cond(
                State.service_msg != "",
                rx.callout(State.service_msg, icon="info", width="100%", size="1"),
            ),
            rx.button(
                rx.hstack(rx.text("Guardar serviços"), rx.icon("check", size=18), align="center"),
                on_click=State.save_services,
                size="3",
                width="100%",
                border_radius="14px",
            ),
            rx.divider(),
            rx.hstack(
                rx.vstack(
                    rx.text("Marcações semanais", weight="bold", color=INK, size="2"),
                    muted("Deixe os clientes repetir a mesma marcação todas as semanas.", size="1"),
                    spacing="0",
                    align="start",
                ),
                rx.spacer(),
                rx.switch(
                    checked=State.allow_recurring,
                    on_change=State.toggle_allow_recurring,
                ),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.cond(
                State.allow_recurring,
                rx.hstack(
                    muted("Máximo de semanas por marcação", size="1"),
                    rx.spacer(),
                    rx.select(
                        State.max_weeks_options,
                        value=State.max_recurring_weeks,
                        on_change=State.set_max_recurring_weeks,
                        size="2",
                    ),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
            ),
            rx.cond(
                State.recurring_msg != "",
                rx.callout(State.recurring_msg, icon="info", width="100%", size="1"),
            ),
            spacing="4",
            width="100%",
        )
    )


def _preset_chip(value, current, on_pick) -> rx.Component:
    """A round quick-pick colour; the current one wears a ring."""
    is_on = current == value
    return rx.box(
        on_click=on_pick(value),
        width="1.7rem",
        height="1.7rem",
        background=value,
        border_radius="50%",
        cursor="pointer",
        box_shadow=rx.cond(
            is_on,
            f"0 0 0 2px {CARD}, 0 0 0 4px {BRAND}",
            f"inset 0 0 0 1px {BORDER}",
        ),
        transition="box-shadow 0.15s ease",
    )


def color_field(label: str, value, on_change, presets) -> rx.Component:
    """A native colour picker plus quick-pick presets, for one colour."""
    return rx.vstack(
        rx.hstack(
            rx.text(label, weight="medium", size="2", color=INK),
            rx.spacer(),
            rx.text(value, size="1", color=MUTED, font_family="monospace"),
            width="100%",
            align="center",
        ),
        rx.hstack(
            rx.el.input(
                type="color",
                value=value,
                on_change=on_change,
                style={
                    "width": "3rem",
                    "height": "2.6rem",
                    "border": "none",
                    "background": "none",
                    "padding": "0",
                    "cursor": "pointer",
                    "flexShrink": "0",
                },
            ),
            rx.flex(
                rx.foreach(presets, lambda c: _preset_chip(c, value, on_change)),
                wrap="wrap",
                gap="2",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align="start",
    )


def logo_field() -> rx.Component:
    """Show the current logo and let the owner pick a new one (applied on save)."""
    return rx.vstack(
        rx.text("Logótipo", weight="medium", size="2", color=INK),
        rx.hstack(
            rx.image(
                src=State.logo_src,
                height="3.2rem",
                width="3.2rem",
                object_fit="contain",
                border_radius="10px",
                background=CARD,
                padding="4px",
                box_shadow=f"inset 0 0 0 1px {BORDER}",
            ),
            rx.upload(
                rx.hstack(
                    rx.icon("upload", size=16, color=BRAND_TEXT),
                    rx.text("Escolher imagem", size="2", color=BRAND_TEXT),
                    align="center",
                    spacing="2",
                ),
                id="logo_upload",
                accept={
                    "image/png": [".png"],
                    "image/jpeg": [".jpg", ".jpeg"],
                    "image/webp": [".webp"],
                },
                max_files=1,
                on_drop=State.upload_logo(
                    cast(Any, rx.upload_files(upload_id="logo_upload"))
                ),
                border=f"1px dashed {BORDER}",
                border_radius="12px",
                padding="0.6rem 0.9rem",
                cursor="pointer",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.cond(State.logo_msg != "", muted(State.logo_msg)),
        muted("PNG, JPEG ou WEBP — quadrado fica melhor (máx. 2 MB)."),
        spacing="2",
        width="100%",
        align="start",
    )


def headline_field() -> rx.Component:
    """Let the owner set the welcome shown on the sign-in page."""
    return rx.vstack(
        rx.text("Frase de entrada", weight="medium", size="2", color=INK),
        rx.input(
            value=State.headline,
            on_change=State.set_headline,
            placeholder="A sua cadeira está à espera",
            max_length=80,
            size="3",
            width="100%",
        ),
        muted("Aparece na página de início de sessão."),
        spacing="2",
        width="100%",
        align="start",
    )


def appearance_card() -> rx.Component:
    """The owner picks two colours, a logo and the welcome; the page updates live."""
    return card(
        rx.vstack(
            panel_title("Aparência", "Cores, logótipo e frase — mudam em direto"),
            color_field("Cor principal", State.brand, State.set_brand, State.brand_presets),
            color_field(
                "Fundo",
                State.background,
                State.set_background,
                State.background_presets,
            ),
            logo_field(),
            headline_field(),
            muted("As mudanças aparecem já; guarde para as aplicar a todos os visitantes."),
            rx.cond(
                State.theme_msg != "",
                rx.callout(State.theme_msg, icon="info", width="100%"),
            ),
            rx.button(
                rx.hstack(rx.text("Guardar"), rx.icon("check", size=18), align="center"),
                on_click=State.save_theme,
                size="3",
                width="100%",
                border_radius="14px",
            ),
            spacing="4",
            width="100%",
        )
    )


# --- profile (edit your own details) -------------------------------------


def profile_card() -> rx.Component:
    """Any signed-in user can edit their own name and phone number here."""
    return card(
        rx.vstack(
            panel_title("Os seus dados", "Mantenha o seu nome e contacto atualizados"),
            rx.input(
                placeholder="O seu nome",
                value=State.profile_name,
                on_change=State.set_profile_name,
                size="3",
                width="100%",
            ),
            rx.input(
                placeholder="Telemóvel (opcional)",
                type="tel",
                value=State.profile_phone,
                on_change=State.set_profile_phone,
                size="3",
                width="100%",
            ),
            rx.cond(
                State.profile_msg != "",
                rx.callout(State.profile_msg, icon="info", width="100%"),
            ),
            rx.button(
                rx.hstack(rx.text("Guardar"), rx.icon("check", size=18), align="center"),
                on_click=State.save_profile,
                size="3",
                width="100%",
                border_radius="14px",
            ),
            rx.separator(size="4"),
            rx.text("Alterar palavra-passe", weight="medium", size="2", color=INK),
            rx.input(
                placeholder="Palavra-passe atual",
                type="password",
                value=State.pw_current,
                on_change=State.set_pw_current,
                size="3",
                width="100%",
            ),
            rx.input(
                placeholder="Nova palavra-passe (mín. 8 caracteres)",
                type="password",
                value=State.pw_new,
                on_change=State.set_pw_new,
                size="3",
                width="100%",
            ),
            rx.cond(
                State.pw_msg != "",
                rx.callout(State.pw_msg, icon="info", width="100%"),
            ),
            rx.button(
                "Alterar palavra-passe",
                on_click=State.change_password,
                variant="soft",
                size="3",
                width="100%",
                border_radius="14px",
            ),
            spacing="4",
            width="100%",
        )
    )


# --- the four views ------------------------------------------------------


def auth_view() -> rx.Component:
    def toggle(label: str, mode: str) -> rx.Component:
        active = State.auth_mode == mode
        return rx.button(
            label,
            on_click=State.set_auth_mode(mode),
            flex="1",
            variant=rx.cond(active, "solid", "soft"),
            size="3",
            border_radius="12px",
        )

    return card(
        rx.vstack(
            rx.hstack(toggle("Entrar", "login"), toggle("Criar conta", "register"), width="100%", spacing="2"),
            rx.cond(
                State.auth_mode == "register",
                rx.input(
                    placeholder="O seu nome",
                    value=State.form_name,
                    on_change=State.set_form_name,
                    size="3",
                    width="100%",
                ),
            ),
            rx.input(
                placeholder="Email",
                type="email",
                value=State.form_email,
                on_change=State.set_form_email,
                size="3",
                width="100%",
            ),
            rx.cond(
                State.auth_mode != "forgot",
                rx.input(
                    placeholder="Palavra-passe",
                    type="password",
                    value=State.form_password,
                    on_change=State.set_form_password,
                    size="3",
                    width="100%",
                ),
            ),
            rx.cond(
                State.auth_error != "",
                muted(
                    State.auth_error,
                    color=rx.cond(
                        State.auth_mode == "forgot",
                        rx.color("grass", 11),
                        rx.color("tomato", 11),
                    ),
                ),
            ),
            rx.cond(
                State.auth_mode == "forgot",
                rx.button(
                    "Enviar email de recuperação",
                    on_click=State.forgot_password,
                    size="4",
                    width="100%",
                    border_radius="14px",
                ),
                rx.button(
                    rx.cond(State.auth_mode == "login", "Entrar", "Criar conta"),
                    on_click=rx.cond(State.auth_mode == "login", State.login, State.register),
                    size="4",
                    width="100%",
                    border_radius="14px",
                ),
            ),
            rx.cond(
                State.auth_mode == "login",
                rx.text(
                    "Esqueceu a palavra-passe?",
                    on_click=State.set_auth_mode("forgot"),
                    size="2",
                    color=BRAND,
                    cursor="pointer",
                    text_align="center",
                    width="100%",
                ),
            ),
            rx.cond(
                State.auth_mode == "forgot",
                rx.text(
                    "Voltar ao início de sessão",
                    on_click=State.set_auth_mode("login"),
                    size="2",
                    color=BRAND,
                    cursor="pointer",
                    text_align="center",
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
        )
    )


def customer_view() -> rx.Component:
    return rx.vstack(
        verify_banner(),
        verify_prompt(),
        booking_message(),
        booking_card(),
        card(
            rx.vstack(
                panel_title("As suas marcações", "Os seus próximos cortes"),
                rx.cond(
                    State.my_appointments,
                    rx.vstack(
                        rx.foreach(State.my_appointments, my_appointment_group),
                        spacing="2",
                        width="100%",
                    ),
                    empty("Ainda sem marcações — marque a primeira acima."),
                ),
                spacing="3",
                width="100%",
            )
        ),
        spacing="5",
        width="100%",
    )


def schedule_card(subtitle: str) -> rx.Component:
    """A read-only agenda: pick a booked day in the strip, see just that day."""
    return card(
        rx.vstack(
            panel_title("A agenda", subtitle),
            rx.cond(
                State.schedule_tabs,
                rx.vstack(
                    rx.hstack(
                        rx.foreach(State.schedule_tabs, schedule_day_chip),
                        overflow_x="auto",
                        width="100%",
                        padding_bottom="0.4rem",
                        spacing="2",
                    ),
                    selected_day_agenda(),
                    spacing="4",
                    width="100%",
                ),
                empty("Sem marcações — as próximas aparecem aqui."),
            ),
            spacing="4",
            width="100%",
        )
    )


def barber_view() -> rx.Component:
    return rx.vstack(
        schedule_card("Os seus próximos dias com marcações"),
        manual_booking_card(),
        working_hours_card(),
        services_card(),
        spacing="5",
        width="100%",
    )


def admin_view() -> rx.Component:
    def picker(barber: Barber) -> rx.Component:
        active = State.admin_barber == barber.id
        return rx.button(
            barber.name,
            on_click=State.view_barber_schedule(barber.id),
            variant=rx.cond(active, "solid", "soft"),
            size="2",
            border_radius="12px",
        )

    return rx.vstack(
        card(
            rx.vstack(
                panel_title("Agenda de quem?", "Escolha um barbeiro para ver o seu dia"),
                rx.flex(rx.foreach(State.barbers, picker), wrap="wrap", gap="2"),
                spacing="3",
                width="100%",
            )
        ),
        schedule_card("Os próximos dias com marcações"),
        manual_booking_card(),
        working_hours_card(),
        services_card(),
        appearance_card(),
        rx.link(
            rx.hstack(
                rx.icon("settings", size=16),
                rx.text("Abrir a consola de administração", weight="medium"),
                align="center",
                spacing="2",
            ),
            href=State.admin_url,
            is_external=True,
            color=BRAND_TEXT,
        ),
        spacing="5",
        width="100%",
    )
