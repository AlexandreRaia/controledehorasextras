"""Sessao, perfis e regras de quem pode fazer o que."""
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

PERFIL_ADMIN = "Administrador"
PERFIL_RH = "RH"
PERFIL_GESTOR = "Gestor"
PERFIL_OPERACOES = "Operacoes"

PERFIS = [PERFIL_ADMIN, PERFIL_RH, PERFIL_GESTOR, PERFIL_OPERACOES]

# Separacao de funcoes: quem lanca nao decide, quem decide nao lanca.
PODE_LANCAR = {PERFIL_RH}
PODE_DECIDIR = {PERFIL_GESTOR}
PODE_CADASTRAR = {PERFIL_ADMIN}

DESCRICAO_PERFIL = {
    PERFIL_ADMIN: "Mantem usuarios, funcionarios e unidades. Consulta lancamentos.",
    PERFIL_RH: "Lanca e corrige as horas enquanto o lancamento estiver pendente.",
    PERFIL_GESTOR: "Aprova ou rejeita horas excedentes e autoriza a hora corrida.",
    PERFIL_OPERACOES: "Somente consulta e relatorios.",
}


def hash_senha(senha):
    return generate_password_hash(senha)


def confere_senha(hash_armazenado, senha):
    if not hash_armazenado:
        return False
    try:
        return check_password_hash(hash_armazenado, senha)
    except ValueError:
        return False


def login_usuario(usuario):
    session.clear()
    session["usuario_id"] = usuario["id"]
    session["usuario_nome"] = usuario["nome"]
    session["usuario_login"] = usuario["login"]
    session["perfil"] = usuario["perfil"]
    session.permanent = True


def logout_usuario():
    session.clear()


def usuario_atual():
    if not session.get("usuario_id"):
        return None
    return {
        "id": session["usuario_id"],
        "nome": session.get("usuario_nome"),
        "login": session.get("usuario_login"),
        "perfil": session.get("perfil"),
    }


def perfil_atual():
    return session.get("perfil")


def tem_perfil(*perfis):
    return perfil_atual() in perfis


def pode_lancar():
    return perfil_atual() in PODE_LANCAR


def pode_decidir():
    return perfil_atual() in PODE_DECIDIR


def pode_cadastrar():
    return perfil_atual() in PODE_CADASTRAR


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not usuario_atual():
            flash("Faca login para continuar.", "aviso")
            return redirect(url_for("auth.login", proximo=request.full_path))
        g.usuario = usuario_atual()
        return view(*args, **kwargs)

    return wrapper


def perfil_required(*perfis):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if perfil_atual() not in perfis:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator
