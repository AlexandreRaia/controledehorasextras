"""Tabelas do PostgreSQL e nomes de colunas usados pelo app."""
PERFIS = ["Administrador", "RH", "Gestor", "Operacoes"]
STATUS_APROVACAO = ["Pendente", "Aprovado", "Rejeitado"]
STATUS_HC = ["Nao solicitada", "Pendente", "Autorizada", "Negada"]


def _lista(valores):
    return ", ".join("'" + v + "'" for v in valores)


# Idempotente: roda na partida do app e no tools.setup_db sem apagar nada.
DDL = f"""
CREATE TABLE IF NOT EXISTS unidades (
    id    SERIAL PRIMARY KEY,
    nome  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS funcionarios (
    id          SERIAL PRIMARY KEY,
    nome        TEXT NOT NULL,
    prontuario  TEXT NOT NULL UNIQUE,
    telefone    TEXT NOT NULL DEFAULT '',
    cargo       TEXT NOT NULL DEFAULT '',
    unidade_id  INTEGER REFERENCES unidades(id) ON DELETE SET NULL,
    ativo       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS usuarios (
    id          SERIAL PRIMARY KEY,
    nome        TEXT NOT NULL,
    login       TEXT NOT NULL,
    senha_hash  TEXT NOT NULL DEFAULT '',
    perfil      TEXT NOT NULL CHECK (perfil IN ({_lista(PERFIS)})),
    ativo       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX IF NOT EXISTS usuarios_login_unico ON usuarios (lower(login));

CREATE TABLE IF NOT EXISTS lancamentos (
    id              SERIAL PRIMARY KEY,
    funcionario_id  INTEGER REFERENCES funcionarios(id) ON DELETE SET NULL,
    prontuario      TEXT NOT NULL,
    data            DATE NOT NULL,
    entrada_seg     INTEGER,
    saida_seg       INTEGER,
    excedidas_seg   INTEGER,
    status          TEXT NOT NULL DEFAULT 'Pendente'
                    CHECK (status IN ({_lista(STATUS_APROVACAO)})),
    hc_solicitada   BOOLEAN NOT NULL DEFAULT FALSE,
    hc_status       TEXT NOT NULL DEFAULT 'Nao solicitada'
                    CHECK (hc_status IN ({_lista(STATUS_HC)})),
    obs_rh          TEXT NOT NULL DEFAULT '',
    parecer_gestor  TEXT NOT NULL DEFAULT '',
    unidade         TEXT NOT NULL DEFAULT '',
    lancado_por     TEXT NOT NULL DEFAULT '',
    lancado_em      TIMESTAMPTZ,
    decidido_por    TEXT NOT NULL DEFAULT '',
    decidido_em     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS lancamentos_data ON lancamentos (data);
CREATE INDEX IF NOT EXISTS lancamentos_prontuario_data ON lancamentos (prontuario, data);

-- Um registro por fechamento. Enquanto reaberto_em e nulo, o mes esta fechado;
-- reabrir preenche a reabertura e preserva o historico.
CREATE TABLE IF NOT EXISTS fechamentos (
    id                 SERIAL PRIMARY KEY,
    ano                INTEGER NOT NULL,
    mes                INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
    fechado_por        TEXT NOT NULL,
    fechado_em         TIMESTAMPTZ NOT NULL DEFAULT now(),
    reaberto_por       TEXT NOT NULL DEFAULT '',
    reaberto_em        TIMESTAMPTZ,
    motivo_reabertura  TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS fechamentos_mes_fechado
    ON fechamentos (ano, mes) WHERE reaberto_em IS NULL;
"""

# Colunas de lancamentos que as views gravam. As views montam o payload com
# estas chaves e o repositorio aceita apenas colunas desta lista.
F = {
    "lanc_prontuario": "prontuario",
    "lanc_funcionario": "funcionario_id",
    "lanc_data": "data",
    "lanc_entrada": "entrada_seg",
    "lanc_saida": "saida_seg",
    "lanc_excedidas": "excedidas_seg",
    "lanc_status": "status",
    "lanc_hc_solicitada": "hc_solicitada",
    "lanc_hc_status": "hc_status",
    "lanc_obs_rh": "obs_rh",
    "lanc_parecer": "parecer_gestor",
    "lanc_unidade": "unidade",
    "lanc_lancado_por": "lancado_por",
    "lanc_lancado_em": "lancado_em",
    "lanc_decidido_por": "decidido_por",
    "lanc_decidido_em": "decidido_em",
}
COLUNAS_LANCAMENTO = frozenset(F.values())
