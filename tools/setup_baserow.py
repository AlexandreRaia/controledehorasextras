"""Prepara o Baserow para o app: cria os campos que faltam e os usuarios iniciais.

Uso:
    python -m tools.setup_baserow                # cria campos e usuarios sem senha definida
    python -m tools.setup_baserow --senhas       # gera e mostra senhas novas para todos
    python -m tools.setup_baserow --so-campos    # apenas o esquema, sem mexer em usuarios
"""
import secrets
import sys

from app import schema as S
from app.auth import PERFIL_ADMIN, PERFIL_GESTOR, PERFIL_OPERACOES, PERFIL_RH, hash_senha
from app.baserow import BaserowClient, BaserowError, save_cache
from app.config import Config

USUARIOS_INICIAIS = [
    {"nome": "Alexandre Raia", "login": "alexandre", "perfil": PERFIL_ADMIN},
    {"nome": "Flavio Galisteu", "login": "flavio", "perfil": PERFIL_RH},
    {"nome": "Fernando Cruz", "login": "fernando", "perfil": PERFIL_GESTOR},
    {"nome": "Veridiana", "login": "veridiana", "perfil": PERFIL_OPERACOES},
]


def resolve_tabelas(client):
    ids = {k: v for k, v in Config.TABLE_IDS.items() if v}
    if len(ids) < 4:
        descobertos, db_id = S.discover_tables(client, Config.BASEROW_DATABASE_ID)
        for key, value in descobertos.items():
            ids.setdefault(key, value)
        print(f"Banco de dados Baserow: {db_id}")
    faltando = [S.TABLE_LABELS[k] for k in S.TABLE_LABELS if not ids.get(k)]
    if faltando:
        raise SystemExit(
            "Nao encontrei a(s) tabela(s): " + ", ".join(faltando)
            + ". Preencha os IDs no .env."
        )
    for key, value in ids.items():
        print(f"  {S.TABLE_LABELS[key]:<14} id={value}")
    return ids


def criar_campos(client, ids):
    print("\nConferindo campos...")
    for chave, desejados in S.REQUIRED_FIELDS.items():
        if not desejados:
            continue
        criados = S.ensure_fields(client, ids[chave], desejados)
        rotulo = S.TABLE_LABELS[chave]
        if criados:
            print(f"  {rotulo}: criados {', '.join(criados)}")
        else:
            print(f"  {rotulo}: nada a criar")


def semear_usuarios(client, ids, gerar_senhas):
    print("\nUsuarios de acesso...")
    table_id = ids[S.T_USUARIOS]
    linhas = client.list_rows(table_id)
    por_login = {}
    por_nome = {}
    for linha in linhas:
        login = (linha.get(S.F["user_login"]) or "").strip().lower()
        nome = S.normalize(linha.get(S.F["user_nome"]))
        if login:
            por_login[login] = linha
        if nome:
            por_nome.setdefault(nome, linha)

    credenciais = []
    for desejado in USUARIOS_INICIAIS:
        existente = por_login.get(desejado["login"]) or por_nome.get(
            S.normalize(desejado["nome"])
        )
        senha = secrets.token_urlsafe(9) if gerar_senhas else None
        payload = {
            S.F["user_nome"]: desejado["nome"],
            S.F["user_login"]: desejado["login"],
            S.F["user_perfil"]: desejado["perfil"],
            S.F["user_ativo"]: True,
        }
        if senha:
            payload[S.F["user_hash"]] = hash_senha(senha)

        if existente:
            tem_hash = bool((existente.get(S.F["user_hash"]) or "").strip())
            if not senha and not tem_hash:
                senha = secrets.token_urlsafe(9)
                payload[S.F["user_hash"]] = hash_senha(senha)
            client.update_row(table_id, existente["id"], payload)
            acao = "atualizado"
        else:
            if not senha:
                senha = secrets.token_urlsafe(9)
                payload[S.F["user_hash"]] = hash_senha(senha)
            client.create_row(table_id, payload)
            acao = "criado"

        print(f"  {desejado['nome']:<18} {desejado['perfil']:<14} {acao}")
        if senha:
            credenciais.append((desejado["login"], senha, desejado["perfil"]))

    if credenciais:
        print("\n" + "=" * 62)
        print("ANOTE AGORA. As senhas nao serao mostradas de novo.")
        print("=" * 62)
        for login, senha, perfil in credenciais:
            print(f"  login: {login:<12} senha: {senha:<16} perfil: {perfil}")
        print("=" * 62)
        print("Troque as senhas na tela de Usuarios apos o primeiro acesso.")


def main():
    argumentos = set(sys.argv[1:])
    gerar_senhas = "--senhas" in argumentos
    so_campos = "--so-campos" in argumentos

    print(f"Baserow: {Config.BASEROW_URL}")
    client = BaserowClient(
        Config.BASEROW_URL,
        email=Config.BASEROW_EMAIL,
        password=Config.BASEROW_PASSWORD,
        token=Config.BASEROW_TOKEN,
    )
    try:
        ids = resolve_tabelas(client)
        criar_campos(client, ids)
        save_cache({"table_ids": ids, "database_id": Config.BASEROW_DATABASE_ID})
        if not so_campos:
            semear_usuarios(client, ids, gerar_senhas)
    except BaserowError as erro:
        raise SystemExit(f"\nErro no Baserow: {erro}")
    print("\nPronto. Inicie o app com: python run.py")


if __name__ == "__main__":
    main()
