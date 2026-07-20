"""Configuration read from the environment — one set of values per shop.

Almost nothing has a default: a missing value stops the app at startup instead
of letting it run misconfigured. The only exceptions are the optional SMTP
authentication settings, which are off by default so dev mail servers work
without extra configuration.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    shop_name: str
    shop_timezone: str
    database_url: str
    jwt_secret: str
    owner_email: str
    owner_name: str
    owner_password: str

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str
    # Base URL the app is reached at, used to build links in emails.
    public_base_url: str
    # Frontend URL used for email links (reset password, etc).
    # Defaults to public_base_url if not set (works when backend proxies frontend).
    frontend_url: str = ""
    # SMTP for transactional email; an empty host disables sending.
    smtp_host: str
    smtp_port: int
    smtp_from: str
    # SMTP authentication and transport security. These are optional: dev mail
    # servers like Mailpit need no login and no TLS, so they default to off.
    # In production, set all three to relay through a real mailbox provider.
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False

    # The shop's brand palette as two colours the owner picks from the UI (any
    # hex). Everything else — text, cards, borders — is derived from these for
    # guaranteed legibility, in light or dark. These are just the *defaults*;
    # the live values are stored in the database.
    shop_brand: str = "#9e7b53"  # buttons, links, highlights
    shop_background: str = "#f6f1e9"  # the page (light or dark)

    # Headline shown on the sign-in page. The owner can change it live from the
    # UI; this is just the default and the fallback before anything is saved.
    # Set to an empty string for no headline.
    shop_headline: str = "A sua cadeira está à espera"

    # Optional path to a logo image used to seed the database on first start.
    # Leave empty to use the bundled default; the owner can always replace the
    # logo later from the UI (it is stored in the database, not on disk).
    shop_logo_path: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore
