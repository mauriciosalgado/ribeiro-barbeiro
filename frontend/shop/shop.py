"""The booking site: one warm, mobile-first page that adapts to who's looking.

Signed out you see a sign-in card; signed in you get the view for your role —
customer, barber, or the shop owner. The layout is a single centred column so
it reads the same on a phone as on a laptop.
"""

import reflex as rx
from reflex.style import set_color_mode

from shop.state import PUBLIC_API_URL, State
from shop.ui import CARD, INK, PAPER, SHADOW
from shop.views import admin_view, auth_view, barber_view, customer_view, profile_card


def brand() -> rx.Component:
    return rx.hstack(
        rx.image(
            src=State.logo_src,
            height="2.4rem",
            width="2.4rem",
            object_fit="contain",
            border_radius="10px",
            background="white",
            padding="2px",
        ),
        rx.heading(State.shop_name, size="5", weight="bold", color=INK),
        align="center",
        spacing="3",
    )


def account() -> rx.Component:
    """Right side of the bar when signed in: who you are, and a way out."""
    role_label = rx.match(
        State.role,
        ("admin", "Dono"),
        ("barber", "Barbeiro"),
        "Cliente",
    )
    return rx.hstack(
        rx.badge(role_label, variant="soft", radius="full"),
        rx.text(State.user_name, weight="medium", color=INK, size="2"),
        rx.icon_button(
            rx.icon("log-out", size=18),
            on_click=State.logout,
            variant="ghost",
            aria_label="Terminar sessão",
        ),
        align="center",
        spacing="3",
    )


def top_bar() -> rx.Component:
    return rx.hstack(
        brand(),
        rx.cond(State.logged_in, account()),
        justify="between",
        align="center",
        width="100%",
        max_width="640px",
        padding="0.9rem 1.25rem",
    )


def hero() -> rx.Component:
    """A short, owner-configurable welcome shown only to signed-out visitors.

    The logo already lives in the top bar, so the sign-in page stays focused on
    a single centred headline above the form. If the owner clears the headline
    the space is kept so the form doesn't jump up against the navigation.
    """
    return rx.box(
        rx.cond(
            State.headline != "",
            rx.heading(
                State.headline,
                size="8",
                color=INK,
                text_align="center",
                width="100%",
            ),
        ),
        width="100%",
        text_align="center",
        padding_y="1rem",
    )


def body() -> rx.Component:
    return rx.cond(
        State.logged_in,
        rx.vstack(
            rx.match(
                State.role,
                ("admin", admin_view()),
                ("barber", barber_view()),
                customer_view(),
            ),
            profile_card(),
            spacing="5",
            width="100%",
        ),
        rx.vstack(hero(), auth_view(), spacing="5", width="100%"),
    )


def color_mode_driver() -> rx.Component:
    """Keep Reflex's color mode in step with the owner's background choice.

    Radix reads its light/dark tokens from the document's color mode, not from
    our ``appearance`` prop. We render one of two hidden markers depending on
    whether the background is dark; when the choice flips, the old marker
    unmounts and the new one mounts, firing ``set_color_mode`` so every Radix
    surface (badges, dropdowns, portals) repaints legibly.
    """
    return rx.cond(
        State.is_dark,
        rx.box(display="none", on_mount=set_color_mode("dark")),
        rx.box(display="none", on_mount=set_color_mode("light")),
    )


def index() -> rx.Component:
    return rx.theme(
        rx.el.style(State.theme_css),
        color_mode_driver(),
        rx.box(
            rx.box(
                top_bar(),
                width="100%",
                display="flex",
                justify_content="center",
                background=CARD,
                backdrop_filter="blur(8px)",
                box_shadow=SHADOW,
                position="sticky",
                top="0",
                z_index="10",
            ),
            rx.box(
                rx.vstack(
                    rx.cond(
                        State.error != "",
                        rx.callout(
                            State.error, icon="triangle-alert", color_scheme="red", width="100%"
                        ),
                    ),
                    body(),
                    spacing="5",
                    width="100%",
                    max_width="480px",
                ),
                width="100%",
                display="flex",
                justify_content="center",
                padding="1.5rem 1.25rem 3rem",
            ),
            class_name="shop-root",
            min_height="100vh",
            width="100%",
            background=PAPER,
        ),
        # Radix reads light/dark tokens from the document color mode, which the
        # hidden ``color_mode_driver`` keeps in sync with the chosen background;
        # "inherit" lets this Theme follow it. Our two colours become CSS
        # variables (via the <style> above, scoped to .shop-root), including the
        # Radix accent tokens — so a colour change from the UI re-themes the
        # whole page live, and for every visitor once saved. Text/cards/borders
        # are derived for legibility (see shop/ui.py).
        appearance="inherit",
        accent_color="bronze",  # a base; overridden by the --accent-* vars
        gray_color="sand",
        radius="large",
        has_background=False,
    )


# The favicon follows the shop's logo: point it at the backend, which serves the
# current logo (falling back to the bundled default). The browser refreshes it
# on load, so replacing the logo updates the tab icon without a redeploy.
app = rx.App(
    head_components=[
        rx.el.link(rel="icon", href=f"{PUBLIC_API_URL}/settings/logo"),
    ]
)
app.add_page(index, route="/", title="Marcar · Barbearia", on_load=[State.init, State.refresh])


def reset_password_page() -> rx.Component:
    """Standalone page linked from the password-reset email."""
    return rx.theme(
        rx.center(
            rx.vstack(
                rx.heading("Nova palavra-passe", size="5"),
                rx.cond(
                    State.reset_done,
                    rx.vstack(
                        rx.callout(State.reset_msg, icon="check", color_scheme="grass", width="100%"),
                        rx.link("Ir para o início de sessão", href="/"),
                        spacing="3",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.input(
                            placeholder="Nova palavra-passe (mín. 8 caracteres)",
                            type="password",
                            value=State.reset_new_password,
                            on_change=State.set_reset_new_password,
                            size="3",
                            width="100%",
                        ),
                        rx.cond(
                            State.reset_msg != "",
                            rx.callout(State.reset_msg, icon="alert-triangle", color_scheme="tomato", width="100%"),
                        ),
                        rx.button(
                            "Definir palavra-passe",
                            on_click=State.submit_reset,
                            size="4",
                            width="100%",
                        ),
                        spacing="4",
                        width="100%",
                    ),
                ),
                spacing="4",
                width="100%",
                max_width="380px",
                padding="2rem",
            ),
            min_height="100vh",
        ),
    )


app.add_page(
    reset_password_page,
    route="/reset-password",
    title="Repor palavra-passe",
    on_load=[State.load_reset_token],
)
