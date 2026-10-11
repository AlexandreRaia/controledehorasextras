"""Conexao com o PostgreSQL."""
import atexit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import schema as S


class DBError(RuntimeError):
    """Falha de conexao ou de consulta no banco."""


class Database:
    """Pool de conexoes. Uma instancia por processo."""

    def __init__(self, url, tamanho_max=5):
        if not url:
            raise DBError("DATABASE_URL nao configurada no .env.")
        self.pool = ConnectionPool(
            url,
            min_size=1,
            max_size=tamanho_max,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
            check=ConnectionPool.check_connection,
            open=False,
        )
        try:
            self.pool.open(wait=True, timeout=15)
        except Exception as exc:  # PoolTimeout nao herda de psycopg.Error
            self.pool.close()
            raise DBError(f"Nao consegui conectar ao PostgreSQL: {exc}") from exc
        atexit.register(self.fecha)

    def _executa(self, sql, params, como):
        try:
            with self.pool.connection() as conn:
                cur = conn.execute(sql, params)
                if como == "todos":
                    return cur.fetchall()
                if como == "um":
                    return cur.fetchone()
                return cur.rowcount
        except psycopg.Error as exc:
            raise DBError(str(exc).strip()) from exc

    def todos(self, sql, params=None):
        return self._executa(sql, params, "todos")

    def um(self, sql, params=None):
        return self._executa(sql, params, "um")

    def executa(self, sql, params=None):
        return self._executa(sql, params, "nada")

    def cria_tabelas(self):
        try:
            with self.pool.connection() as conn:
                conn.execute(S.DDL)
        except psycopg.Error as exc:
            raise DBError(f"Falha ao criar as tabelas: {exc}") from exc

    def fecha(self):
        self.pool.close()
