"""A tiny key/value store for settings the owner can change at runtime.

Most configuration comes from the environment (one value per shop, fixed at
deploy time). A few things — like the brand colours and the logo — are nicer to
tweak live from the UI, so they live here in the database instead.

Text settings use `value`; binary settings (the logo) use `data` + `content_type`.
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""
    # Binary payload (e.g. logo image). Only set for non-text settings.
    content_type: str | None = None
    data: bytes | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __str__(self) -> str:
        if self.content_type:
            return f"{self.key} ({self.content_type})"
        return f"{self.key} = {self.value}"
