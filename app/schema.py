"""Nomes de tabelas/campos no Baserow e criacao automatica do que falta."""
import unicodedata

# --------------------------------------------------------------- nomes fixos
T_UNIDADES = "unidades"
T_FUNCIONARIOS = "funcionarios"
T_USUARIOS = "usuarios"
T_LANCAMENTOS = "lancamentos"

TABLE_LABELS = {
    T_UNIDADES: "Unidades",
    T_FUNCIONARIOS: "Funcionarios",
    T_USUARIOS: "Usuarios",
    T_LANCAMENTOS: "Lancamentos",
}

# Campos criados pelo app quando ainda nao existem na tabela.
PERFIS = ["Administrador", "RH", "Gestor", "Operacoes"]
STATUS_APROVACAO = ["Pendente", "Aprovado", "Rejeitado"]
STATUS_HC = ["Nao solicitada", "Pendente", "Autorizada", "Negada"]

REQUIRED_FIELDS = {
    T_UNIDADES: [],
    T_FUNCIONARIOS: [
        {"name": "Ativo", "type": "boolean"},
    ],
    T_USUARIOS: [
        {"name": "Login", "type": "text"},
        {"name": "SenhaHash", "type": "long_text"},
        {
            "name": "Perfil",
            "type": "single_select",
            "select_options": [
                {"value": "Administrador", "color": "dark-blue"},
                {"value": "RH", "color": "dark-green"},
                {"value": "Gestor", "color": "dark-orange"},
                {"value": "Operacoes", "color": "dark-gray"},
            ],
        },
    ],
    T_LANCAMENTOS: [
        {
            "name": "Status",
            "type": "single_select",
            "select_options": [
                {"value": "Pendente", "color": "yellow"},
                {"value": "Aprovado", "color": "green"},
                {"value": "Rejeitado", "color": "red"},
            ],
        },
        {
            "name": "HC Status",
            "type": "single_select",
            "select_options": [
                {"value": "Nao solicitada", "color": "light-gray"},
                {"value": "Pendente", "color": "yellow"},
                {"value": "Autorizada", "color": "green"},
                {"value": "Negada", "color": "red"},
            ],
        },
        {"name": "Observacao RH", "type": "long_text"},
        {"name": "Parecer Gestor", "type": "long_text"},
        {"name": "Unidade", "type": "text"},
        {"name": "Lancado Por", "type": "text"},
        {"name": "Lancado Em", "type": "date", "date_format": "EU",
         "date_include_time": True, "date_time_format": "24"},
        {"name": "Decidido Por", "type": "text"},
        {"name": "Decidido Em", "type": "date", "date_format": "EU",
         "date_include_time": True, "date_time_format": "24"},
    ],
}

# Campos que ja existem no Baserow e sao usados pelo app.
F = {
    "unidade_nome": "Name",
    "func_nome": "Name",
    "func_prontuario": "Prontuario",
    "func_telefone": "Phone",
    "func_cargo": "Job role",
    "func_unidade": "Unidade",
    "func_ativo": "Ativo",
    "user_nome": "Name",
    "user_login": "Login",
    "user_hash": "SenhaHash",
    "user_perfil": "Perfil",
    "user_ativo": "Active",
    "lanc_prontuario": "Prontuario",
    "lanc_funcionario": "Nome",
    "lanc_data": "Data",
    "lanc_entrada": "Entrada",
    "lanc_saida": "Saida",
    "lanc_trabalhadas": "Horas Trabalhadas",
    "lanc_excedidas": "Horas Excedidas",
    "lanc_status": "Status",
    "lanc_hc_solicitada": "HC",
    "lanc_hc_status": "HC Status",
    "lanc_obs_rh": "Observacao RH",
    "lanc_parecer": "Parecer Gestor",
    "lanc_unidade": "Unidade",
    "lanc_lancado_por": "Lancado Por",
    "lanc_lancado_em": "Lancado Em",
    "lanc_decidido_por": "Decidido Por",
    "lanc_decidido_em": "Decidido Em",
}


def normalize(text):
    """Minusculas, sem acento e sem espacos nas pontas."""
    if text is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(text))
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    return txt.strip().lower()


TABLE_ALIASES = {
    T_UNIDADES: {"unidades", "unidade", "units", "unit"},
    T_FUNCIONARIOS: {"funcionarios", "funcionario", "colaboradores", "motoristas"},
    T_USUARIOS: {"usuarios", "usuario", "users"},
    T_LANCAMENTOS: {"lancamentos", "lancamento", "apontamentos", "horas"},
}


def discover_tables(client, database_id=None):
    """Descobre os ids das quatro tabelas pelo nome. Retorna (ids, database_id)."""
    databases = []
    if database_id:
        databases = [database_id]
    else:
        for app_ in client.list_applications() or []:
            if app_.get("type") == "database":
                databases.append(app_["id"])

    found = {}
    used_db = None
    for db_id in databases:
        tables = client.list_tables(db_id) or []
        hits = {}
        for table in tables:
            key_name = normalize(table.get("name"))
            for key, aliases in TABLE_ALIASES.items():
                if key_name in aliases:
                    hits[key] = table["id"]
        if len(hits) > len(found):
            found, used_db = hits, db_id
    return found, used_db


def ensure_fields(client, table_id, wanted):
    """Cria os campos que faltam. Devolve a lista de nomes criados."""
    existing = {normalize(f["name"]): f for f in client.list_fields(table_id) or []}
    created = []
    for spec in wanted:
        if normalize(spec["name"]) in existing:
            continue
        client.create_field(table_id, dict(spec))
        created.append(spec["name"])
    return created
