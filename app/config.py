"""Configuracao lida do ambiente (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _int(name, default=None):
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-inseguro-troque-no-env"

    # postgresql://usuario:senha@host:5432/banco
    DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

    JORNADA_PADRAO_SEGUNDOS = int(float(os.getenv("JORNADA_PADRAO_HORAS") or 8) * 3600)
    ALMOCO_SEGUNDOS = int(float(os.getenv("ALMOCO_HORAS") or 1) * 3600)
    TIMEZONE_OFFSET = _int("TIMEZONE_OFFSET", -3)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 10
