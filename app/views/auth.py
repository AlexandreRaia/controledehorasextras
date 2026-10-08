"""Login e logout."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import get_repo
from ..auth import confere_senha, login_required, login_usuario, logout_usuario, usuario_atual

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if usuario_atual():
        return redirect(url_for("relatorios.inicio"))

    if request.method == "POST":
        login_informado = (request.form.get("login") or "").strip()
        senha = request.form.get("senha") or ""
        repo = get_repo()
        usuario = repo.usuario_por_login(login_informado)

        if not usuario or not confere_senha(usuario["hash"], senha):
            flash("Login ou senha invalidos.", "erro")
        elif not usuario["ativo"]:
            flash("Usuario inativo. Procure o administrador.", "erro")
        elif not usuario["perfil"]:
            flash("Usuario sem perfil definido. Procure o administrador.", "erro")
        else:
            login_usuario(usuario)
            proximo = request.args.get("proximo") or ""
            if proximo.startswith("/") and not proximo.startswith("//"):
                return redirect(proximo)
            return redirect(url_for("relatorios.inicio"))

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_usuario()
    flash("Sessao encerrada.", "ok")
    return redirect(url_for("auth.login"))
