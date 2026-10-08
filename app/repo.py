"""Camada de dados: traduz linhas do Baserow em dicionarios do dominio."""
from . import schema as S
from .baserow import BaserowClient, BaserowError, load_cache, save_cache
from .utils import (
    calcula_jornada,
    format_date_br,
    format_datetime_br,
    link_ids,
    link_values,
    parse_date,
    parse_duration,
    select_value,
)

READ_ONLY_TYPES = {
    "formula", "lookup", "rollup", "count", "uuid", "autonumber",
    "created_on", "last_modified", "created_by", "last_modified_by",
}

CAMPO_DATA = S.F["lanc_data"]

# Versoes diferentes do Baserow nomeiam e formatam o filtro de data de outro
# jeito, e a versao errada devolve zero linha sem acusar erro. Por isso o
# dialeto e descoberto na primeira consulta e conferido contra a contagem total.
DIALETOS_DATA = [
    {
        "nome": "moderno",
        "depois": "date_is_on_or_after",
        "antes": "date_is_on_or_before",
        "valor": lambda data: f"UTC?{data}?exact_date",
    },
    {
        "nome": "legado",
        "depois": "date_after_or_equal",
        "antes": "date_before_or_equal",
        "valor": lambda data: data,
    },
]


class Repo:
    """Acesso as quatro tabelas. Uma instancia por processo."""

    def __init__(self, config):
        self.config = config
        self.client = BaserowClient(
            config.BASEROW_URL,
            email=config.BASEROW_EMAIL,
            password=config.BASEROW_PASSWORD,
            token=config.BASEROW_TOKEN,
        )
        self.table_ids = {}
        self.database_id = config.BASEROW_DATABASE_ID
        self.readonly_fields = {}
        self.campo_aprovado_legado = None
        self._dialeto = "nao testado"
        self._bootstrap()

    # ------------------------------------------------------------- bootstrap
    def _bootstrap(self):
        cache = load_cache()
        ids = dict(cache.get("table_ids") or {})
        for key, value in self.config.TABLE_IDS.items():
            if value:
                ids[key] = value
        faltando = [k for k in S.TABLE_LABELS if not ids.get(k)]
        if faltando:
            descobertos, db_id = S.discover_tables(
                self.client, self.database_id or cache.get("database_id")
            )
            ids.update({k: v for k, v in descobertos.items() if not ids.get(k)})
            self.database_id = self.database_id or db_id
        self.table_ids = {k: ids.get(k) for k in S.TABLE_LABELS}
        ausentes = [S.TABLE_LABELS[k] for k, v in self.table_ids.items() if not v]
        if ausentes:
            raise BaserowError(
                "Nao encontrei no Baserow a(s) tabela(s): " + ", ".join(ausentes)
                + ". Informe os IDs no .env (TABLE_UNIDADES, TABLE_FUNCIONARIOS, "
                "TABLE_USUARIOS, TABLE_LANCAMENTOS)."
            )
        save_cache({"table_ids": self.table_ids, "database_id": self.database_id})
        self._load_field_metadata()

    def _load_field_metadata(self):
        for key, table_id in self.table_ids.items():
            try:
                campos = self.client.list_fields(table_id) or []
            except BaserowError:
                self.readonly_fields[key] = set()
                continue
            self.readonly_fields[key] = {
                f["name"] for f in campos
                if f.get("type") in READ_ONLY_TYPES or f.get("read_only")
            }
            if key == S.T_LANCAMENTOS:
                self.campo_aprovado_legado = next(
                    (
                        f["name"] for f in campos
                        if f.get("type") == "boolean"
                        and S.normalize(f["name"]).startswith("aprova")
                    ),
                    None,
                )

    def _clean(self, table_key, payload):
        """Remove campos somente-leitura antes de gravar."""
        bloqueados = self.readonly_fields.get(table_key, set())
        return {k: v for k, v in payload.items() if k not in bloqueados}

    # -------------------------------------------------------------- unidades
    def unidades(self):
        rows = self.client.list_rows(
            self.table_ids[S.T_UNIDADES], order_by=S.F["unidade_nome"]
        )
        return [{"id": r["id"], "nome": r.get(S.F["unidade_nome"]) or ""} for r in rows]

    def unidade(self, row_id):
        r = self.client.get_row(self.table_ids[S.T_UNIDADES], row_id)
        return {"id": r["id"], "nome": r.get(S.F["unidade_nome"]) or ""}

    def unidade_criar(self, nome):
        payload = self._clean(S.T_UNIDADES, {S.F["unidade_nome"]: nome})
        return self.client.create_row(self.table_ids[S.T_UNIDADES], payload)

    def unidade_atualizar(self, row_id, nome):
        payload = self._clean(S.T_UNIDADES, {S.F["unidade_nome"]: nome})
        return self.client.update_row(self.table_ids[S.T_UNIDADES], row_id, payload)

    def unidade_excluir(self, row_id):
        self.client.delete_row(self.table_ids[S.T_UNIDADES], row_id)

    # ----------------------------------------------------------- funcionarios
    def _map_funcionario(self, r):
        bruto_unidade = r.get(S.F["func_unidade"])
        nomes_unidade = link_values(bruto_unidade)
        return {
            "id": r["id"],
            "nome": r.get(S.F["func_nome"]) or "",
            "prontuario": (r.get(S.F["func_prontuario"]) or "").strip(),
            "telefone": r.get(S.F["func_telefone"]) or "",
            "cargo": r.get(S.F["func_cargo"]) or "",
            "unidade": ", ".join(nomes_unidade) or (
                bruto_unidade if isinstance(bruto_unidade, str) else ""
            ),
            "unidade_ids": link_ids(bruto_unidade),
            "ativo": r.get(S.F["func_ativo"]) is not False,
        }

    def funcionarios(self, somente_ativos=False):
        rows = self.client.list_rows(
            self.table_ids[S.T_FUNCIONARIOS], order_by=S.F["func_nome"]
        )
        itens = [self._map_funcionario(r) for r in rows]
        if somente_ativos:
            itens = [f for f in itens if f["ativo"]]
        return itens

    def funcionario(self, row_id):
        return self._map_funcionario(
            self.client.get_row(self.table_ids[S.T_FUNCIONARIOS], row_id)
        )

    def funcionario_por_prontuario(self, prontuario):
        alvo = (prontuario or "").strip()
        if not alvo:
            return None
        for f in self.funcionarios():
            if f["prontuario"] == alvo:
                return f
        return None

    def _payload_funcionario(self, dados):
        payload = {
            S.F["func_nome"]: dados.get("nome"),
            S.F["func_prontuario"]: dados.get("prontuario"),
            S.F["func_telefone"]: dados.get("telefone"),
            S.F["func_cargo"]: dados.get("cargo"),
            S.F["func_ativo"]: bool(dados.get("ativo")),
        }
        unidade_id = dados.get("unidade_id")
        payload[S.F["func_unidade"]] = [int(unidade_id)] if unidade_id else []
        return self._clean(S.T_FUNCIONARIOS, payload)

    def funcionario_criar(self, dados):
        return self.client.create_row(
            self.table_ids[S.T_FUNCIONARIOS], self._payload_funcionario(dados)
        )

    def funcionario_atualizar(self, row_id, dados):
        return self.client.update_row(
            self.table_ids[S.T_FUNCIONARIOS], row_id, self._payload_funcionario(dados)
        )

    def funcionario_excluir(self, row_id):
        self.client.delete_row(self.table_ids[S.T_FUNCIONARIOS], row_id)

    # --------------------------------------------------------------- usuarios
    def _map_usuario(self, r):
        return {
            "id": r["id"],
            "nome": r.get(S.F["user_nome"]) or "",
            "login": (r.get(S.F["user_login"]) or "").strip(),
            "hash": r.get(S.F["user_hash"]) or "",
            "perfil": select_value(r.get(S.F["user_perfil"])) or "",
            "ativo": r.get(S.F["user_ativo"]) is not False,
        }

    def usuarios(self):
        rows = self.client.list_rows(
            self.table_ids[S.T_USUARIOS], order_by=S.F["user_nome"]
        )
        return [self._map_usuario(r) for r in rows]

    def usuario(self, row_id):
        return self._map_usuario(self.client.get_row(self.table_ids[S.T_USUARIOS], row_id))

    def usuario_por_login(self, login):
        alvo = (login or "").strip().lower()
        if not alvo:
            return None
        for u in self.usuarios():
            if u["login"].lower() == alvo:
                return u
        return None

    def usuario_criar(self, dados):
        payload = self._clean(S.T_USUARIOS, {
            S.F["user_nome"]: dados.get("nome"),
            S.F["user_login"]: dados.get("login"),
            S.F["user_hash"]: dados.get("hash"),
            S.F["user_perfil"]: dados.get("perfil"),
            S.F["user_ativo"]: bool(dados.get("ativo")),
        })
        return self.client.create_row(self.table_ids[S.T_USUARIOS], payload)

    def usuario_atualizar(self, row_id, dados):
        payload = {
            S.F["user_nome"]: dados.get("nome"),
            S.F["user_login"]: dados.get("login"),
            S.F["user_perfil"]: dados.get("perfil"),
            S.F["user_ativo"]: bool(dados.get("ativo")),
        }
        if dados.get("hash"):
            payload[S.F["user_hash"]] = dados["hash"]
        return self.client.update_row(
            self.table_ids[S.T_USUARIOS], row_id, self._clean(S.T_USUARIOS, payload)
        )

    def usuario_excluir(self, row_id):
        self.client.delete_row(self.table_ids[S.T_USUARIOS], row_id)

    # ------------------------------------------------------------ lancamentos
    def _map_lancamento(self, r):
        entrada = parse_duration(r.get(S.F["lanc_entrada"]))
        saida = parse_duration(r.get(S.F["lanc_saida"]))
        hc_status = select_value(r.get(S.F["lanc_hc_status"])) or "Nao solicitada"
        permanencia, almoco, trabalhadas, excedidas = calcula_jornada(
            entrada, saida, self.config.JORNADA_PADRAO_SEGUNDOS,
            self.config.ALMOCO_SEGUNDOS, hc_autorizada=hc_status == "Autorizada",
        )
        # Quanto o excedente viraria se o gestor autorizasse a hora corrida.
        _, _, _, excedidas_com_hc = calcula_jornada(
            entrada, saida, self.config.JORNADA_PADRAO_SEGUNDOS,
            self.config.ALMOCO_SEGUNDOS, hc_autorizada=True,
        )
        data_iso = parse_date(r.get(CAMPO_DATA))
        return {
            "id": r["id"],
            "prontuario": (r.get(S.F["lanc_prontuario"]) or "").strip(),
            "funcionario": ", ".join(link_values(r.get(S.F["lanc_funcionario"]))),
            "funcionario_ids": link_ids(r.get(S.F["lanc_funcionario"])),
            "data": data_iso,
            "data_br": format_date_br(data_iso),
            "entrada_seg": entrada,
            "saida_seg": saida,
            "permanencia_seg": permanencia,
            "almoco_seg": almoco,
            "trabalhadas_seg": trabalhadas,
            "excedidas_seg": excedidas,
            "excedidas_com_hc_seg": excedidas_com_hc,
            "status": select_value(r.get(S.F["lanc_status"])) or "Pendente",
            "hc_solicitada": bool(r.get(S.F["lanc_hc_solicitada"])),
            "hc_status": hc_status,
            "obs_rh": r.get(S.F["lanc_obs_rh"]) or "",
            "parecer": r.get(S.F["lanc_parecer"]) or "",
            "unidade": r.get(S.F["lanc_unidade"]) or "",
            "lancado_por": r.get(S.F["lanc_lancado_por"]) or "",
            "lancado_em": format_datetime_br(
                r.get(S.F["lanc_lancado_em"]), self.config.TIMEZONE_OFFSET
            ),
            "decidido_por": r.get(S.F["lanc_decidido_por"]) or "",
            "decidido_em": format_datetime_br(
                r.get(S.F["lanc_decidido_em"]), self.config.TIMEZONE_OFFSET
            ),
        }

    def _dialeto_data(self):
        """Descobre qual dialeto de filtro de data esta instancia entende.

        Cada candidato e conferido pedindo tudo ate uma data distante: se a
        contagem bater com o total da tabela, o filtro funciona de verdade.
        Nenhum servindo, o filtro passa a ser feito aqui mesmo.
        """
        if self._dialeto != "nao testado":
            return self._dialeto

        table_id = self.table_ids[S.T_LANCAMENTOS]
        self._dialeto = None
        try:
            total = self.client.count_rows(table_id)
            for dialeto in DIALETOS_DATA:
                chave = "filter__" + CAMPO_DATA + "__" + dialeto["antes"]
                contagem = self.client.count_rows(
                    table_id, {chave: dialeto["valor"]("2999-12-31")}
                )
                if contagem == total:
                    self._dialeto = dialeto
                    break
        except BaserowError:
            self._dialeto = None
        return self._dialeto

    def lancamentos(self, inicio=None, fim=None, prontuario=None, status=None,
                    unidade=None, hc_status=None):
        table_id = self.table_ids[S.T_LANCAMENTOS]
        dialeto = self._dialeto_data() if (inicio or fim) else None
        filtros = {}
        if dialeto and inicio:
            filtros["filter__" + CAMPO_DATA + "__" + dialeto["depois"]] = \
                dialeto["valor"](inicio)
        if dialeto and fim:
            filtros["filter__" + CAMPO_DATA + "__" + dialeto["antes"]] = \
                dialeto["valor"](fim)
        try:
            rows = self.client.list_rows(
                table_id, filters=filtros, order_by="-" + CAMPO_DATA
            )
        except BaserowError:
            # Filtro recusado: traz tudo e deixa o recorte para o passo abaixo.
            self._dialeto = None
            rows = self.client.list_rows(table_id, order_by="-" + CAMPO_DATA)

        itens = [self._map_lancamento(r) for r in rows]
        if inicio:
            itens = [i for i in itens if i["data"] and i["data"] >= inicio]
        if fim:
            itens = [i for i in itens if i["data"] and i["data"] <= fim]
        if prontuario:
            alvo = prontuario.strip()
            itens = [i for i in itens if i["prontuario"] == alvo]
        if status:
            itens = [i for i in itens if i["status"] == status]
        if hc_status:
            itens = [i for i in itens if i["hc_status"] == hc_status]
        if unidade:
            itens = [i for i in itens if i["unidade"] == unidade]
        itens.sort(key=lambda i: (i["data"] or "", i["funcionario"]), reverse=True)
        return itens

    def lancamento(self, row_id):
        return self._map_lancamento(
            self.client.get_row(self.table_ids[S.T_LANCAMENTOS], row_id)
        )

    def lancamento_criar(self, payload):
        return self.client.create_row(
            self.table_ids[S.T_LANCAMENTOS], self._clean(S.T_LANCAMENTOS, payload)
        )

    def lancamento_atualizar(self, row_id, payload):
        return self.client.update_row(
            self.table_ids[S.T_LANCAMENTOS], row_id, self._clean(S.T_LANCAMENTOS, payload)
        )

    def lancamento_excluir(self, row_id):
        self.client.delete_row(self.table_ids[S.T_LANCAMENTOS], row_id)

    def existe_lancamento(self, prontuario, data_iso, ignorar_id=None):
        iguais = self.lancamentos(inicio=data_iso, fim=data_iso, prontuario=prontuario)
        for item in iguais:
            if item["id"] != ignorar_id:
                return item
        return None
