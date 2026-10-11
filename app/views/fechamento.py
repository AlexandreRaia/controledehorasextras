"""Fechamento mensal. O gestor fecha; so o administrador reabre."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .. import get_repo
from ..auth import PODE_FECHAR, PODE_REABRIR, login_required, perfil_required, usuario_atual
from ..config import Config
from ..utils import MESES, local_today

bp = Blueprint("fechamento", __name__, url_prefix="/fechamento")

NOME_MES = dict(MESES)


def _ano():
    hoje = local_today(Config.TIMEZONE_OFFSET)
    try:
        ano = int(request.args.get("ano") or hoje.year)
        if not 2020 <= ano <= 2100:
            raise ValueError
    except ValueError:
        ano = hoje.year
    return ano


@bp.route("/")
@login_required
def listar():
    repo = get_repo()
    ano = _ano()
    hoje = local_today(Config.TIMEZONE_OFFSET)
    registros = repo.fechamentos_do_ano(ano)
    vigentes = {r["mes"]: r for r in registros if not r["reaberto_em"]}
    pendencias = repo.pendencias_do_ano(ano)
    meses = [
        {
            "numero": numero,
            "nome": nome,
            "fechamento": vigentes.get(numero),
            "pendencias": pendencias.get(numero, 0),
            "futuro": (ano, numero) > (hoje.year, hoje.month),
        }
        for numero, nome in MESES
    ]
    return render_template(
        "fechamento/listar.html",
        ano=ano,
        meses=meses,
        reaberturas=[r for r in registros if r["reaberto_em"]],
    )


@bp.route("/<int:ano>/<int:mes>/fechar", methods=["POST"])
@perfil_required(*PODE_FECHAR)
def fechar(ano, mes):
    if not 1 <= mes <= 12:
        abort(404)
    repo = get_repo()
    destino = redirect(url_for("fechamento.listar", ano=ano))
    hoje = local_today(Config.TIMEZONE_OFFSET)
    if (ano, mes) > (hoje.year, hoje.month):
        flash("Nao e possivel fechar um mes que ainda nao comecou.", "erro")
        return destino

    if repo.fechar_mes(ano, mes, usuario_atual()["nome"]):
        flash(
            f"{NOME_MES[mes]} de {ano} fechado. Lancamentos e decisoes deste mes "
            "estao bloqueados.",
            "ok",
        )
    elif repo.fechamento(ano, mes):
        flash("Este mes ja esta fechado.", "aviso")
    else:
        n = repo.pendencias_do_ano(ano).get(mes, 0)
        flash(
            f"Ainda ha {n} lancamento(s) esperando decisao em {NOME_MES[mes]}. "
            "Decida todos antes de fechar.",
            "erro",
        )
    return destino


@bp.route("/<int:ano>/<int:mes>/reabrir", methods=["POST"])
@perfil_required(*PODE_REABRIR)
def reabrir(ano, mes):
    if not 1 <= mes <= 12:
        abort(404)
    repo = get_repo()
    motivo = (request.form.get("motivo") or "").strip()
    if len(motivo) < 5:
        flash("Informe o motivo da reabertura (ao menos 5 caracteres).", "erro")
    elif repo.reabrir_mes(ano, mes, usuario_atual()["nome"], motivo):
        flash(f"{NOME_MES[mes]} de {ano} reaberto.", "ok")
    else:
        flash("Este mes nao esta fechado.", "aviso")
    return redirect(url_for("fechamento.listar", ano=ano))
