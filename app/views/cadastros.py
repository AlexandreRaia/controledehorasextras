"""Manutencao de unidades, funcionarios e usuarios. Exclusivo do administrador."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import get_repo
from ..auth import PERFIL_ADMIN, PERFIS, hash_senha, perfil_required, usuario_atual

bp = Blueprint("cadastros", __name__, url_prefix="/cadastros")


# --------------------------------------------------------------------- unidades
@bp.route("/unidades")
@perfil_required(PERFIL_ADMIN)
def unidades():
    repo = get_repo()
    return render_template("cadastros/unidades.html", itens=repo.unidades())


@bp.route("/unidades/salvar", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def unidade_salvar():
    repo = get_repo()
    nome = (request.form.get("nome") or "").strip()
    row_id = request.form.get("id")
    if not nome:
        flash("Informe o nome da unidade.", "erro")
    elif row_id:
        repo.unidade_atualizar(int(row_id), nome)
        flash("Unidade atualizada.", "ok")
    else:
        repo.unidade_criar(nome)
        flash("Unidade cadastrada.", "ok")
    return redirect(url_for("cadastros.unidades"))


@bp.route("/unidades/<int:row_id>/excluir", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def unidade_excluir(row_id):
    repo = get_repo()
    unidade = repo.unidade(row_id)
    vinculados = [f for f in repo.funcionarios() if unidade["nome"] in (f["unidade"] or "")]
    if vinculados:
        flash(
            f"A unidade {unidade['nome']} tem {len(vinculados)} funcionario(s) vinculado(s). "
            "Transfira-os antes de excluir.",
            "erro",
        )
    else:
        repo.unidade_excluir(row_id)
        flash("Unidade excluida.", "ok")
    return redirect(url_for("cadastros.unidades"))


# ----------------------------------------------------------------- funcionarios
@bp.route("/funcionarios")
@perfil_required(PERFIL_ADMIN)
def funcionarios():
    repo = get_repo()
    return render_template(
        "cadastros/funcionarios.html",
        itens=repo.funcionarios(),
        unidades=repo.unidades(),
    )


@bp.route("/funcionarios/salvar", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def funcionario_salvar():
    repo = get_repo()
    row_id = request.form.get("id")
    dados = {
        "nome": (request.form.get("nome") or "").strip(),
        "prontuario": (request.form.get("prontuario") or "").strip(),
        "telefone": (request.form.get("telefone") or "").strip(),
        "cargo": (request.form.get("cargo") or "").strip(),
        "unidade_id": request.form.get("unidade_id") or None,
        "ativo": bool(request.form.get("ativo")),
        "jornada_horas": 12 if request.form.get("jornada_horas") == "12" else 8,
    }

    erros = []
    if not dados["nome"]:
        erros.append("Informe o nome do funcionario.")
    if not dados["prontuario"]:
        erros.append("Informe o prontuario.")
    else:
        existente = repo.funcionario_por_prontuario(dados["prontuario"])
        if existente and str(existente["id"]) != str(row_id or ""):
            erros.append(f"O prontuario {dados['prontuario']} ja esta em uso.")

    if erros:
        for erro in erros:
            flash(erro, "erro")
    elif row_id:
        repo.funcionario_atualizar(int(row_id), dados)
        flash("Funcionario atualizado.", "ok")
    else:
        repo.funcionario_criar(dados)
        flash("Funcionario cadastrado.", "ok")
    return redirect(url_for("cadastros.funcionarios"))


@bp.route("/funcionarios/<int:row_id>/excluir", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def funcionario_excluir(row_id):
    repo = get_repo()
    funcionario = repo.funcionario(row_id)
    lancamentos = repo.lancamentos(prontuario=funcionario["prontuario"])
    if lancamentos:
        flash(
            f"{funcionario['nome']} tem {len(lancamentos)} lancamento(s) no historico. "
            "Marque como inativo em vez de excluir.",
            "erro",
        )
    else:
        repo.funcionario_excluir(row_id)
        flash("Funcionario excluido.", "ok")
    return redirect(url_for("cadastros.funcionarios"))


# --------------------------------------------------------------------- usuarios
@bp.route("/usuarios")
@perfil_required(PERFIL_ADMIN)
def usuarios():
    repo = get_repo()
    return render_template(
        "cadastros/usuarios.html", itens=repo.usuarios(), perfis=PERFIS
    )


@bp.route("/usuarios/salvar", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def usuario_salvar():
    repo = get_repo()
    row_id = request.form.get("id")
    senha = request.form.get("senha") or ""
    dados = {
        "nome": (request.form.get("nome") or "").strip(),
        "login": (request.form.get("login") or "").strip(),
        "perfil": request.form.get("perfil") or "",
        "ativo": bool(request.form.get("ativo")),
    }

    erros = []
    if not dados["nome"]:
        erros.append("Informe o nome do usuario.")
    if not dados["login"]:
        erros.append("Informe o login.")
    else:
        existente = repo.usuario_por_login(dados["login"])
        if existente and str(existente["id"]) != str(row_id or ""):
            erros.append(f"O login {dados['login']} ja esta em uso.")
    if dados["perfil"] not in PERFIS:
        erros.append("Escolha um perfil valido.")
    if senha and len(senha) < 6:
        erros.append("A senha precisa de ao menos 6 caracteres.")
    if not row_id and not senha:
        erros.append("Informe a senha inicial do usuario.")

    atual = usuario_atual()
    if row_id and atual and str(atual["id"]) == str(row_id):
        if dados["perfil"] != PERFIL_ADMIN or not dados["ativo"]:
            erros.append(
                "Voce nao pode remover o proprio acesso de administrador."
            )

    if senha:
        dados["hash"] = hash_senha(senha)

    if erros:
        for erro in erros:
            flash(erro, "erro")
    elif row_id:
        repo.usuario_atualizar(int(row_id), dados)
        flash("Usuario atualizado.", "ok")
    else:
        repo.usuario_criar(dados)
        flash("Usuario cadastrado.", "ok")
    return redirect(url_for("cadastros.usuarios"))


@bp.route("/usuarios/<int:row_id>/excluir", methods=["POST"])
@perfil_required(PERFIL_ADMIN)
def usuario_excluir(row_id):
    repo = get_repo()
    atual = usuario_atual()
    if atual and str(atual["id"]) == str(row_id):
        flash("Voce nao pode excluir o proprio usuario.", "erro")
        return redirect(url_for("cadastros.usuarios"))

    admins = [
        u for u in repo.usuarios()
        if u["perfil"] == PERFIL_ADMIN and u["ativo"] and u["id"] != row_id
    ]
    if not admins:
        flash("Mantenha ao menos um administrador ativo.", "erro")
        return redirect(url_for("cadastros.usuarios"))

    repo.usuario_excluir(row_id)
    flash("Usuario excluido.", "ok")
    return redirect(url_for("cadastros.usuarios"))
