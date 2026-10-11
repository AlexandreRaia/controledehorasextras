"""Prepara o PostgreSQL para o app: cria as tabelas e os usuarios iniciais.

Uso:
    python -m tools.setup_db                # cria tabelas e usuarios que faltam
    python -m tools.setup_db --senhas       # gera e mostra senhas novas para todos
    python -m tools.setup_db --so-tabelas   # apenas o esquema, sem mexer em usuarios
"""
import secrets
import sys
from urllib.parse import urlparse

from app.auth import PERFIL_ADMIN, PERFIL_GESTOR, PERFIL_OPERACOES, PERFIL_RH, hash_senha
from app.config import Config
from app.db import Database, DBError

USUARIOS_INICIAIS = [
    {"nome": "Alexandre Raia", "login": "alexandre", "perfil": PERFIL_ADMIN},
    {"nome": "Flavio Galisteu", "login": "flavio", "perfil": PERFIL_RH},
    {"nome": "Fernando Cruz", "login": "fernando", "perfil": PERFIL_GESTOR},
    {"nome": "Veridiana", "login": "veridiana", "perfil": PERFIL_OPERACOES},
]


def semear_usuarios(db, gerar_senhas):
    print("\nUsuarios de acesso...")
    credenciais = []
    for desejado in USUARIOS_INICIAIS:
        existente = db.um(
            "SELECT id, senha_hash FROM usuarios WHERE lower(login) = %s",
            (desejado["login"],),
        )
        senha = None
        if gerar_senhas or not existente or not existente["senha_hash"]:
            senha = secrets.token_urlsafe(9)

        if existente:
            if senha:
                db.executa(
                    "UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                    (hash_senha(senha), existente["id"]),
                )
            acao = "senha renovada" if senha else "ja existe"
        else:
            db.executa(
                "INSERT INTO usuarios (nome, login, senha_hash, perfil, ativo)"
                " VALUES (%s, %s, %s, %s, TRUE)",
                (desejado["nome"], desejado["login"], hash_senha(senha), desejado["perfil"]),
            )
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
    alvo = urlparse(Config.DATABASE_URL)
    print(f"PostgreSQL: {alvo.username}@{alvo.hostname}:{alvo.port or 5432}{alvo.path}")
    try:
        db = Database(Config.DATABASE_URL)
        db.cria_tabelas()
        tabelas = db.todos(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'public' ORDER BY table_name"
        )
        print("Tabelas: " + ", ".join(t["table_name"] for t in tabelas))
        if "--so-tabelas" not in argumentos:
            semear_usuarios(db, "--senhas" in argumentos)
        db.fecha()
    except DBError as erro:
        raise SystemExit(f"\nErro no banco: {erro}")
    print("\nPronto. Inicie o app com: python run.py")


if __name__ == "__main__":
    main()
