import os
from functools import lru_cache

from pydantic import BaseModel, Field, model_validator


def _flag(name, default=True):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


class EnvConfig(BaseModel):
    port: int = Field(default=4455, ge=1, le=65535)
    api_key: str = ""
    debounce_minutes: int = Field(default=20, ge=1, le=1440)
    max_postpone_minutes: int = Field(default=120, ge=1, le=10080)
    overwrite_all: bool = True
    music_dir: str = "/music"
    movies_dir: str = "/movies"
    tv_dir: str = "/tv"

    @model_validator(mode="after")
    def _timers(self):
        if self.debounce_minutes >= self.max_postpone_minutes:
            raise ValueError("CMM_DEBOUNCE_MINUTES must be less than CMM_MAX_POSTPONE_MINUTES")
        return self


@lru_cache(maxsize=1)
def load():
    return EnvConfig(
        port=_int("CMM_PORT", 4455),
        api_key=(os.environ.get("CMM_API_KEY") or "").strip(),
        debounce_minutes=_int("CMM_DEBOUNCE_MINUTES", 20),
        max_postpone_minutes=_int("CMM_MAX_POSTPONE_MINUTES", 120),
        overwrite_all=_flag("CMM_OVERWRITE_ALL"),
        music_dir=os.environ.get("MUSIC_DIR", "/music"),
        movies_dir=os.environ.get("MOVIES_DIR", "/movies"),
        tv_dir=os.environ.get("TV_DIR", "/tv"),
    )
