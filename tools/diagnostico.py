"""Confere a conexao com o Baserow e diz exatamente o que ainda falta.

Uso:
    python -m tools.diagnostico
"""
from app import schema as S
from app.baserow import BaserowClient, BaserowError, nova_sessao
from app.config import Config

SESSAO = nova_sessao()

OK = "[ok]"
FALTA = "[falta]"
ERRO = "[erro]"


def testa_instancia():
    print(f"\n1. Instancia: {Config.BASEROW_URL}")
    try:
        resp = SESSAO.get(f"{Config.BASEROW_URL}/api/settings/", timeout=20)
    except Exception as exc:
        print(f"   {ERRO} nao respondeu: {exc}")
        return False
    if resp.status_code == 200:
        print(f"   {OK} respondendo")
        return True
    print(f"   {ERRO} HTTP {resp.status_code}")
    return False


def testa_token():
    print("\n2. Token de banco de dados")
    if not Config.BASEROW_TOKEN:
        print(f"   {FALTA} BASEROW_TOKEN vazio no .env")
        return
    cabecalho = {"Authorization": f"Token {Config.BASEROW_TOKEN}"}
    ids = {k: v for k, v in Config.TABLE_IDS.items() if v}
    if not ids:
        print("   IDs das tabelas nao informados no .env. Testando o id 1 so para")
        print("   descobrir se o token tem alguma permissao.")
        ids = {"teste": 1}

    pendencias = 0
    for chave, table_id in ids.items():
        rotulo = S.TABLE_LABELS.get(chave, chave)
        try:
            resp = SESSAO.get(
                f"{Config.BASEROW_URL}/api/database/rows/table/{table_id}/",
                params={"user_field_names": "true", "size": 1},
                headers=cabecalho,
                timeout=30,
            )
        except Exception as exc:
            print(f"   {ERRO} {rotulo} (id {table_id}): sem resposta. {exc}")
            continue
        if resp.status_code == 200:
            dados = resp.json()
            print(f"   {OK} {rotulo} (id {table_id}): {dados.get('count')} linha(s)")
        elif "ERROR_NO_PERMISSION_TO_TABLE" in resp.text:
            print(f"   {FALTA} {rotulo} (id {table_id}): token sem permissao na tabela")
            pendencias += 1
        else:
            print(f"   {ERRO} {rotulo} (id {table_id}): HTTP {resp.status_code} {resp.text[:120]}")

    if pendencias:
        print("   Para liberar: Baserow > foto do perfil > Settings > Database tokens,")
        print("   abra o token e marque Create, Read, Update e Delete no banco de dados.")


def testa_jwt():
    print("\n3. Acesso ao esquema (e-mail e senha)")
    if not (Config.BASEROW_EMAIL and Config.BASEROW_PASSWORD):
        print(f"   {FALTA} BASEROW_EMAIL e BASEROW_PASSWORD vazios no .env")
        print("   Sem eles o app nao consegue criar os campos novos nem descobrir")
        print("   os ids das tabelas sozinho.")
        return None

    client = BaserowClient(
        Config.BASEROW_URL,
        email=Config.BASEROW_EMAIL,
        password=Config.BASEROW_PASSWORD,
    )
    try:
        client.jwt()
    except BaserowError as exc:
        print(f"   {ERRO} {exc}")
        return None
    print(f"   {OK} autenticado como {Config.BASEROW_EMAIL}")

    ids, db_id = S.discover_tables(client, Config.BASEROW_DATABASE_ID)
    print(f"\n4. Tabelas encontradas (banco de dados {db_id})")
    for chave, rotulo in S.TABLE_LABELS.items():
        if ids.get(chave):
            print(f"   {OK} {rotulo:<14} id={ids[chave]}")
        else:
            print(f"   {FALTA} {rotulo:<14} nao encontrada pelo nome")

    print("\n5. Campos por tabela")
    for chave, table_id in ids.items():
        campos = client.list_fields(table_id) or []
        nomes = {S.normalize(c["name"]) for c in campos}
        print(f"\n   {S.TABLE_LABELS[chave]} (id {table_id})")
        for campo in campos:
            print(f"      - {campo['name']} ({campo['type']})")
        faltando = [
            e["name"] for e in S.REQUIRED_FIELDS.get(chave, [])
            if S.normalize(e["name"]) not in nomes
        ]
        if faltando:
            print(f"      {FALTA} a criar: {', '.join(faltando)}")
        else:
            print(f"      {OK} nenhum campo a criar")

    if ids:
        print("\n6. Cole no .env para dispensar a descoberta automatica")
        if db_id:
            print(f"   BASEROW_DATABASE_ID={db_id}")
        for chave, rotulo in S.TABLE_LABELS.items():
            if ids.get(chave):
                print(f"   TABLE_{rotulo.upper()}={ids[chave]}")
    return ids


def main():
    print("=" * 66)
    print("Diagnostico da conexao com o Baserow")
    print("=" * 66)
    if not testa_instancia():
        return
    testa_token()
    testa_jwt()
    print("\n" + "=" * 66)
    print("Resolvido o que estiver marcado como falta, rode:")
    print("   python -m tools.setup_baserow --senhas")
    print("=" * 66)


if __name__ == "__main__":
    main()
