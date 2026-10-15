"""Decisao do gestor sobre horas excedentes e hora corrida.

O gestor grava apenas Status, HC Status, Parecer e a trilha de quem decidiu.
Entrada, saida, data e funcionario pertencem ao RH e nunca sao tocados aqui.
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .. import get_repo
from .. import schema as S
from ..auth import PERFIL_GESTOR, perfil_required, usuario_atual
from ..config import Config
from ..utils import (
    agrupa_por_funcionario,
    calcula_jornada,
    format_duration,
    iso_now_utc,
    local_today,
    month_bounds,
)

bp = Blueprint("aprovacoes", __name__, url_prefix="/aprovacoes")

STATUS_VALIDOS = {"Aprovado", "Rejeitado"}
HC_VALIDOS = {"Autorizada", "Negada", "Pendente"}


def _grava_decisao(repo, item, status=None, hc_decisao=None, parecer=None):
    """Grava o que o gestor decidiu sobre um lancamento.

    Cada parte e opcional: da para decidir so as horas, so a hora corrida, ou
    as duas juntas. O gestor nao mexe em entrada, saida nem data. A unica hora
    que ele move e o excedente, e so porque a hora corrida que ele mesmo decide
    diz se a hora de almoco conta ou nao.
    """
    usuario = usuario_atual()
    payload = {
        S.F["lanc_decidido_por"]: usuario["nome"] if usuario else "",
        S.F["lanc_decidido_em"]: iso_now_utc(),
    }
    if status in STATUS_VALIDOS:
        payload[S.F["lanc_status"]] = status
    if parecer is not None:
        payload[S.F["lanc_parecer"]] = parecer

    hc_final = item["hc_status"]
    if hc_decisao in HC_VALIDOS:
        payload[S.F["lanc_hc_status"]] = hc_decisao
        hc_final = hc_decisao

    jornada, almoco = Config.parametros_jornada(item["jornada_horas"])
    _, _, _, excedidas = calcula_jornada(
        item["entrada_seg"], item["saida_seg"], jornada, almoco,
        hc_autorizada=item["hc_solicitada"] and hc_final != "Negada",
        fora_escala=item["fora_escala"],
    )
    # O excedente digitado pelo RH vale no lugar do calculado: nao se regrava.
    if not item["ajustado"] and excedidas is not None and excedidas != item["excedidas_seg"]:
        payload[S.F["lanc_excedidas"]] = excedidas
    repo.lancamento_atualizar(item["id"], payload)


def _decide(repo, item, status, hc_decisao, parecer):
    """Decisao completa, usada pela tela Analisar."""
    if not (item["hc_solicitada"] and hc_decisao in HC_VALIDOS):
        hc_decisao = None
    _grava_decisao(repo, item, status, hc_decisao, parecer)


def _de_volta():
    destino = request.form.get("voltar") or request.referrer
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return destino
    return url_for("aprovacoes.listar")


@bp.route("/")
@perfil_required(PERFIL_GESTOR)
def listar():
    repo = get_repo()
    hoje = local_today(Config.TIMEZONE_OFFSET)
    try:
        ano = int(request.args.get("ano") or hoje.year)
        mes = int(request.args.get("mes") or hoje.month)
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    inicio, fim = month_bounds(ano, mes)
    status = request.args.get("status", "Pendente")
    prontuario = (request.args.get("prontuario") or "").strip()

    itens = repo.lancamentos(
        inicio=inicio, fim=fim, prontuario=prontuario or None, status=status or None
    )
    fechamento = repo.fechamento(ano, mes)
    for i in itens:
        i["fechado"] = bool(fechamento)
    # Sem horas excedentes e sem HC nao ha o que decidir.
    relevantes = [
        i for i in itens if (i["excedidas_seg"] or 0) != 0 or i["hc_solicitada"]
    ]
    somente_relevantes = request.args.get("todos") != "1"
    mostrados = relevantes if somente_relevantes else itens

    return render_template(
        "aprovacoes/listar.html",
        fechamento=fechamento,
        grupos=agrupa_por_funcionario(mostrados),
        itens=mostrados,
        ano=ano,
        mes=mes,
        status=status,
        prontuario=prontuario,
        funcionarios=repo.funcionarios(),
        somente_relevantes=somente_relevantes,
        total_excedido=sum(i["excedidas_seg"] or 0 for i in mostrados),
    )


@bp.route("/<int:row_id>", methods=["GET", "POST"])
@perfil_required(PERFIL_GESTOR)
def decidir(row_id):
    repo = get_repo()
    item = repo.lancamento(row_id)
    if repo.mes_fechado_data(item["data"]):
        flash("O mes deste lancamento ja foi fechado. Fale com o administrador.", "erro")
        return redirect(url_for("aprovacoes.listar"))

    if request.method == "POST":
        status = request.form.get("decisao")
        if status not in STATUS_VALIDOS:
            flash("Escolha aprovar ou rejeitar.", "erro")
            return render_template("aprovacoes/decidir.html", item=item)

        hc_decisao = request.form.get("hc_decisao")
        parecer = (request.form.get("parecer") or "").strip()
        if status == "Rejeitado" and not parecer:
            flash("Informe o motivo da rejeicao.", "erro")
            return render_template("aprovacoes/decidir.html", item=item)
        if item["hc_solicitada"] and hc_decisao not in HC_VALIDOS:
            flash("Decida tambem sobre a hora corrida.", "erro")
            return render_template("aprovacoes/decidir.html", item=item)

        _decide(repo, item, status, hc_decisao, parecer)
        flash(f"Lancamento {status.lower()}.", "ok")
        return redirect(url_for("aprovacoes.listar"))

    return render_template("aprovacoes/decidir.html", item=item)


@bp.route("/<int:row_id>/horas", methods=["POST"])
@perfil_required(PERFIL_GESTOR)
def decidir_horas(row_id):
    """Botao de aprovar ou reprovar as horas excedentes, direto na lista."""
    repo = get_repo()
    valor = request.form.get("valor")
    if valor not in STATUS_VALIDOS:
        flash("Decisao invalida.", "erro")
        return redirect(_de_volta())

    item = repo.lancamento(row_id)
    _grava_decisao(repo, item, status=valor)
    flash(
        f"{item['funcionario'] or item['prontuario']} em {item['data_br']}: "
        f"horas {'aprovadas' if valor == 'Aprovado' else 'rejeitadas'}.",
        "ok",
    )
    return redirect(_de_volta())


@bp.route("/<int:row_id>/hc", methods=["POST"])
@perfil_required(PERFIL_GESTOR)
def decidir_hc(row_id):
    """Botao de autorizar ou negar a hora corrida, direto na lista."""
    repo = get_repo()
    valor = request.form.get("valor")
    if valor not in {"Autorizada", "Negada"}:
        flash("Decisao invalida para a hora corrida.", "erro")
        return redirect(_de_volta())

    item = repo.lancamento(row_id)
    if not item["hc_solicitada"]:
        flash("A hora corrida nao foi pedida pelo RH neste lancamento.", "erro")
        return redirect(_de_volta())
    _grava_decisao(repo, item, hc_decisao=valor)
    depois = repo.lancamento(row_id)
    flash(
        f"{item['funcionario'] or item['prontuario']} em {item['data_br']}: "
        f"hora corrida {valor.lower()}. Excedente agora "
        f"{format_duration(depois['excedidas_seg'])}.",
        "ok",
    )
    return redirect(_de_volta())
