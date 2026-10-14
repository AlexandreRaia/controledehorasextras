"""Camada de dados: consultas no PostgreSQL devolvendo dicionarios do dominio."""
from flask import abort

from . import schema as S
from .db import Database, DBError
from .utils import (
    calcula_jornada,
    format_date_br,
    format_datetime_br,
    month_bounds,
    parse_date,
)

# Lancamento que ainda exige uma decisao do gestor: horas excedentes sem
# decisao, ou hora corrida pedida e ainda sem resposta.
SQL_PENDENTE = """
    ((status = 'Pendente' AND (COALESCE(excedidas_seg, 0) > 0 OR hc_solicitada))
     OR (hc_solicitada AND hc_status = 'Pendente'))
"""


class MesFechado(RuntimeError):
    """Gravacao recusada porque o mes do lancamento ja foi fechado."""

    def __init__(self, ano, mes):
        self.ano, self.mes = ano, mes
        super().__init__(f"O mes {mes:02d}/{ano} esta fechado.")

SQL_FUNCIONARIO = """
    SELECT f.id, f.nome, f.prontuario, f.telefone, f.cargo, f.unidade_id, f.ativo,
           f.jornada_horas, COALESCE(u.nome, '') AS unidade
      FROM funcionarios f
      LEFT JOIN unidades u ON u.id = f.unidade_id
"""

SQL_LANCAMENTO = """
    SELECT l.*, COALESCE(f.nome, '') AS funcionario,
           COALESCE(f.jornada_horas, 8) AS jornada_horas
      FROM lancamentos l
      LEFT JOIN funcionarios f ON f.id = l.funcionario_id
"""


def _iso(valor):
    return valor.isoformat() if valor else None


class Repo:
    """Acesso as quatro tabelas. Uma instancia por processo."""

    def __init__(self, config, db=None):
        self.config = config
        self.db = db or Database(config.DATABASE_URL)
        self.db.cria_tabelas()

    # -------------------------------------------------------------- unidades
    def unidades(self):
        return self.db.todos("SELECT id, nome FROM unidades ORDER BY nome")

    def unidade(self, row_id):
        return self._existe(
            self.db.um("SELECT id, nome FROM unidades WHERE id = %s", (row_id,))
        )

    def unidade_criar(self, nome):
        return self.db.um("INSERT INTO unidades (nome) VALUES (%s) RETURNING id", (nome,))

    def unidade_atualizar(self, row_id, nome):
        self.db.executa("UPDATE unidades SET nome = %s WHERE id = %s", (nome, row_id))

    def unidade_excluir(self, row_id):
        self.db.executa("DELETE FROM unidades WHERE id = %s", (row_id,))

    # ----------------------------------------------------------- funcionarios
    @staticmethod
    def _map_funcionario(r):
        return {
            "id": r["id"],
            "nome": r["nome"],
            "prontuario": r["prontuario"],
            "telefone": r["telefone"],
            "cargo": r["cargo"],
            "unidade": r["unidade"],
            "unidade_ids": [r["unidade_id"]] if r["unidade_id"] else [],
            "ativo": r["ativo"],
            "jornada_horas": r["jornada_horas"],
        }

    def funcionarios(self, somente_ativos=False):
        filtro = " WHERE f.ativo" if somente_ativos else ""
        rows = self.db.todos(SQL_FUNCIONARIO + filtro + " ORDER BY f.nome")
        return [self._map_funcionario(r) for r in rows]

    def funcionario(self, row_id):
        r = self._existe(self.db.um(SQL_FUNCIONARIO + " WHERE f.id = %s", (row_id,)))
        return self._map_funcionario(r)

    def funcionario_por_prontuario(self, prontuario):
        alvo = (prontuario or "").strip()
        if not alvo:
            return None
        r = self.db.um(SQL_FUNCIONARIO + " WHERE f.prontuario = %s", (alvo,))
        return self._map_funcionario(r) if r else None

    @staticmethod
    def _valores_funcionario(dados):
        unidade_id = dados.get("unidade_id")
        return (
            dados.get("nome") or "",
            (dados.get("prontuario") or "").strip(),
            dados.get("telefone") or "",
            dados.get("cargo") or "",
            int(unidade_id) if unidade_id else None,
            bool(dados.get("ativo")),
            int(dados.get("jornada_horas") or 8),
        )

    def funcionario_criar(self, dados):
        return self.db.um(
            "INSERT INTO funcionarios"
            " (nome, prontuario, telefone, cargo, unidade_id, ativo, jornada_horas)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            self._valores_funcionario(dados),
        )

    def funcionario_atualizar(self, row_id, dados):
        self.db.executa(
            "UPDATE funcionarios SET nome = %s, prontuario = %s, telefone = %s,"
            " cargo = %s, unidade_id = %s, ativo = %s, jornada_horas = %s WHERE id = %s",
            self._valores_funcionario(dados) + (row_id,),
        )

    def funcionario_excluir(self, row_id):
        self.db.executa("DELETE FROM funcionarios WHERE id = %s", (row_id,))

    # --------------------------------------------------------------- usuarios
    @staticmethod
    def _map_usuario(r):
        return {
            "id": r["id"],
            "nome": r["nome"],
            "login": r["login"],
            "hash": r["senha_hash"],
            "perfil": r["perfil"],
            "ativo": r["ativo"],
        }

    def usuarios(self):
        rows = self.db.todos("SELECT * FROM usuarios ORDER BY nome")
        return [self._map_usuario(r) for r in rows]

    def usuario_por_login(self, login):
        alvo = (login or "").strip().lower()
        if not alvo:
            return None
        r = self.db.um("SELECT * FROM usuarios WHERE lower(login) = %s", (alvo,))
        return self._map_usuario(r) if r else None

    def usuario_criar(self, dados):
        return self.db.um(
            "INSERT INTO usuarios (nome, login, senha_hash, perfil, ativo)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                dados.get("nome"), (dados.get("login") or "").strip(),
                dados.get("hash") or "", dados.get("perfil"), bool(dados.get("ativo")),
            ),
        )

    def usuario_atualizar(self, row_id, dados):
        campos = {
            "nome": dados.get("nome"),
            "login": (dados.get("login") or "").strip(),
            "perfil": dados.get("perfil"),
            "ativo": bool(dados.get("ativo")),
        }
        if dados.get("hash"):
            campos["senha_hash"] = dados["hash"]
        self._atualiza("usuarios", row_id, campos)

    def usuario_excluir(self, row_id):
        self.db.executa("DELETE FROM usuarios WHERE id = %s", (row_id,))

    # ------------------------------------------------------------ lancamentos
    def _map_lancamento(self, r):
        entrada, saida = r["entrada_seg"], r["saida_seg"]
        hc_status = r["hc_status"]
        fora_escala = bool(r["fora_escala"])
        jornada, almoco_cfg = self.config.parametros_jornada(r["jornada_horas"])
        permanencia, almoco, trabalhadas, excedidas = calcula_jornada(
            entrada, saida, jornada, almoco_cfg,
            hc_autorizada=hc_status == "Autorizada", fora_escala=fora_escala,
        )
        # Quanto o excedente viraria se o gestor autorizasse a hora corrida.
        _, _, _, excedidas_com_hc = calcula_jornada(
            entrada, saida, jornada, almoco_cfg,
            hc_autorizada=True, fora_escala=fora_escala,
        )
        data_iso = _iso(r["data"])
        return {
            "id": r["id"],
            "prontuario": r["prontuario"],
            "funcionario": r["funcionario"],
            "funcionario_ids": [r["funcionario_id"]] if r["funcionario_id"] else [],
            "jornada_horas": r["jornada_horas"],
            "fora_escala": fora_escala,
            "data": data_iso,
            "data_br": format_date_br(data_iso),
            "entrada_seg": entrada,
            "saida_seg": saida,
            "permanencia_seg": permanencia,
            "almoco_seg": almoco,
            "trabalhadas_seg": trabalhadas,
            "excedidas_seg": excedidas,
            "excedidas_com_hc_seg": excedidas_com_hc,
            "status": r["status"],
            "hc_solicitada": r["hc_solicitada"],
            "hc_status": hc_status,
            "obs_rh": r["obs_rh"],
            "parecer": r["parecer_gestor"],
            "unidade": r["unidade"],
            "lancado_por": r["lancado_por"],
            "lancado_em": format_datetime_br(
                _iso(r["lancado_em"]), self.config.TIMEZONE_OFFSET
            ),
            "decidido_por": r["decidido_por"],
            "decidido_em": format_datetime_br(
                _iso(r["decidido_em"]), self.config.TIMEZONE_OFFSET
            ),
        }

    def lancamentos(self, inicio=None, fim=None, prontuario=None, status=None,
                    unidade=None, hc_status=None):
        condicoes, params = [], []
        for coluna, operador, valor in (
            ("l.data", ">=", inicio),
            ("l.data", "<=", fim),
            ("l.prontuario", "=", (prontuario or "").strip()),
            ("l.status", "=", status),
            ("l.hc_status", "=", hc_status),
            ("l.unidade", "=", unidade),
        ):
            if valor:
                condicoes.append(f"{coluna} {operador} %s")
                params.append(valor)
        where = (" WHERE " + " AND ".join(condicoes)) if condicoes else ""
        rows = self.db.todos(
            SQL_LANCAMENTO + where + " ORDER BY l.data DESC, funcionario DESC", params
        )
        return [self._map_lancamento(r) for r in rows]

    def lancamento(self, row_id):
        r = self._existe(self.db.um(SQL_LANCAMENTO + " WHERE l.id = %s", (row_id,)))
        return self._map_lancamento(r)

    def lancamento_criar(self, payload):
        self._garante_data_aberta(payload.get(S.F["lanc_data"]))
        campos = self._colunas_lancamento(payload)
        nomes = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        return self.db.um(
            f"INSERT INTO lancamentos ({nomes}) VALUES ({marcas}) RETURNING id",
            list(campos.values()),
        )

    def lancamento_atualizar(self, row_id, payload):
        self._garante_lancamento_aberto(row_id)
        if S.F["lanc_data"] in payload:
            self._garante_data_aberta(payload[S.F["lanc_data"]])
        self._atualiza("lancamentos", row_id, self._colunas_lancamento(payload))

    def lancamento_excluir(self, row_id):
        self._garante_lancamento_aberto(row_id)
        self.db.executa("DELETE FROM lancamentos WHERE id = %s", (row_id,))

    def existe_lancamento(self, prontuario, data_iso, ignorar_id=None):
        r = self.db.um(
            SQL_LANCAMENTO + " WHERE l.prontuario = %s AND l.data = %s"
            " AND l.id IS DISTINCT FROM %s LIMIT 1",
            ((prontuario or "").strip(), data_iso, ignorar_id),
        )
        return self._map_lancamento(r) if r else None

    # ------------------------------------------------------------ fechamento
    def _map_fechamento(self, r):
        tz = self.config.TIMEZONE_OFFSET
        return {
            "id": r["id"],
            "ano": r["ano"],
            "mes": r["mes"],
            "fechado_por": r["fechado_por"],
            "fechado_em": format_datetime_br(_iso(r["fechado_em"]), tz),
            "reaberto_por": r["reaberto_por"],
            "reaberto_em": format_datetime_br(_iso(r["reaberto_em"]), tz),
            "motivo": r["motivo_reabertura"],
        }

    def fechamento(self, ano, mes):
        """O fechamento em vigor do mes, ou None se ele esta aberto."""
        r = self.db.um(
            "SELECT * FROM fechamentos WHERE ano = %s AND mes = %s AND reaberto_em IS NULL",
            (ano, mes),
        )
        return self._map_fechamento(r) if r else None

    def mes_fechado_data(self, data_iso):
        data = parse_date(data_iso)
        if not data:
            return False
        return self.fechamento(int(data[:4]), int(data[5:7])) is not None

    def fechamentos_do_ano(self, ano):
        rows = self.db.todos(
            "SELECT * FROM fechamentos WHERE ano = %s ORDER BY fechado_em DESC", (ano,)
        )
        return [self._map_fechamento(r) for r in rows]

    def pendencias_do_ano(self, ano):
        """Quantos lancamentos ainda esperam decisao, por mes: {mes: quantidade}."""
        rows = self.db.todos(
            "SELECT EXTRACT(MONTH FROM data)::int AS mes, count(*) AS n FROM lancamentos"
            " WHERE data BETWEEN %s AND %s AND " + SQL_PENDENTE + " GROUP BY 1",
            (f"{ano}-01-01", f"{ano}-12-31"),
        )
        return {r["mes"]: r["n"] for r in rows}

    def fechar_mes(self, ano, mes, por):
        """Fecha o mes se nao ha pendencia. False se ja estava fechado ou ha pendencia."""
        inicio, fim = month_bounds(ano, mes)
        r = self.db.um(
            "INSERT INTO fechamentos (ano, mes, fechado_por)"
            " SELECT %s::int, %s::int, %s::text"
            " WHERE NOT EXISTS (SELECT 1 FROM lancamentos"
            "                   WHERE data BETWEEN %s AND %s AND " + SQL_PENDENTE + ")"
            " ON CONFLICT DO NOTHING RETURNING id",
            (ano, mes, por, inicio, fim),
        )
        return r is not None

    def reabrir_mes(self, ano, mes, por, motivo):
        alteradas = self.db.executa(
            "UPDATE fechamentos SET reaberto_por = %s, reaberto_em = now(),"
            " motivo_reabertura = %s WHERE ano = %s AND mes = %s AND reaberto_em IS NULL",
            (por, motivo, ano, mes),
        )
        return alteradas > 0

    def _garante_data_aberta(self, data_iso):
        data = parse_date(data_iso)
        if data and self.mes_fechado_data(data):
            raise MesFechado(int(data[:4]), int(data[5:7]))

    def _garante_lancamento_aberto(self, row_id):
        r = self.db.um(
            "SELECT l.data FROM lancamentos l JOIN fechamentos f"
            " ON f.ano = EXTRACT(YEAR FROM l.data) AND f.mes = EXTRACT(MONTH FROM l.data)"
            " AND f.reaberto_em IS NULL WHERE l.id = %s",
            (row_id,),
        )
        if r:
            raise MesFechado(r["data"].year, r["data"].month)

    # ------------------------------------------------------------- auxiliares
    @staticmethod
    def _colunas_lancamento(payload):
        desconhecidas = set(payload) - S.COLUNAS_LANCAMENTO
        if desconhecidas:
            raise DBError("Colunas desconhecidas: " + ", ".join(sorted(desconhecidas)))
        return dict(payload)

    def _atualiza(self, tabela, row_id, campos):
        """UPDATE com nomes de coluna vindos do proprio codigo, nunca do usuario."""
        if not campos:
            return
        sets = ", ".join(f"{coluna} = %s" for coluna in campos)
        self.db.executa(
            f"UPDATE {tabela} SET {sets} WHERE id = %s", list(campos.values()) + [row_id]
        )

    @staticmethod
    def _existe(row):
        if row is None:
            abort(404)
        return row
