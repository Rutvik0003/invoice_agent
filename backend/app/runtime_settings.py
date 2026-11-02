"""Settings an admin can change in the UI (stored in the database, overriding the environment defaults).

Only operational values are editable (today: the pause between AI requests). Business rules stay in environment
variables, and secrets (API keys) are never stored here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.demo.sandbox import is_demo_engine
from app.models import AppSetting


class EditableSettings(BaseModel):
    """What the Settings screen may change."""

    ai_request_gap_s: float = Field(ge=0, le=120, description="Minimum seconds between two AI requests")


EDITABLE = tuple(EditableSettings.model_fields)


def overrides(engine: Engine) -> dict[str, object]:
    with Session(engine) as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting)) if row.key in EDITABLE}


def effective_settings(engine: Engine, base: Settings | None = None) -> Settings:
    """Environment settings with the values saved in the Settings screen on top. A demo sandbox runs with the
    demo AI settings (Gemini only, demo key)."""
    base = base or get_settings()
    if is_demo_engine(engine):
        base = base.for_demo()
    return base.model_copy(update=overrides(engine))


def current_editable(engine: Engine) -> EditableSettings:
    s = effective_settings(engine)
    return EditableSettings(**{name: getattr(s, name) for name in EDITABLE})


def save_editable(engine: Engine, values: EditableSettings) -> EditableSettings:
    with Session(engine) as session:
        for key, value in values.model_dump().items():
            session.merge(AppSetting(key=key, value=value))
        session.commit()
    return current_editable(engine)
