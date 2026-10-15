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
    # O almoco so e descontado quando a permanencia passa deste tempo (CLT: 6h).
    ALMOCO_A_PARTIR_SEGUNDOS = int(float(os.getenv("ALMOCO_A_PARTIR_HORAS") or 6) * 3600)
    TIMEZONE_OFFSET = _int("TIMEZONE_OFFSET", -3)

    # Plantonista 12x36: jornada de 12 horas, sem hora de almoco a descontar.
    JORNADA_PLANTAO_HORAS = 12

    @classmethod
    def parametros_jornada(cls, jornada_horas):
        """(jornada, almoco) em segundos de quem faz essa jornada diaria."""
        if jornada_horas == cls.JORNADA_PLANTAO_HORAS:
            return cls.JORNADA_PLANTAO_HORAS * 3600, 0
        return cls.JORNADA_PADRAO_SEGUNDOS, cls.ALMOCO_SEGUNDOS

    @classmethod
    def calcula(cls, jornada_horas, entrada, saida, hc_autorizada=False, fora_escala=False):
        """calcula_jornada com a jornada e o almoco de quem faz `jornada_horas`."""
        from .utils import calcula_jornada

        jornada, almoco = cls.parametros_jornada(jornada_horas)
        return calcula_jornada(
            entrada, saida, jornada, almoco, hc_autorizada=hc_autorizada,
            fora_escala=fora_escala, almoco_a_partir=cls.ALMOCO_A_PARTIR_SEGUNDOS,
        )

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 10
