"""Rota inicial, consolidado mensal e exportacao em CSV."""
import csv
import io

from flask import Blueprint, Response, redirect, render_template, request, url_for

from .. import get_repo
from ..auth import login_required, pode_decidir
from ..config import Config
from ..utils import (
    agrupa_por_funcionario,
    format_duration,
    horas_decimais,
    local_today,
    month_bounds,
)

bp = Blueprint("relatorios", __name__)


def _periodo():
    hoje = local_today(Config.TIMEZONE_OFFSET)
    try:
        ano = int(request.args.get("ano") or hoje.year)
        mes = int(request.args.get("mes") or hoje.month)
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    inicio, fim = month_bounds(ano, mes)
    return ano, mes, inicio, fim


@bp.route("/")
@login_required
def inicio():
    """A raiz leva cada perfil direto para a tela que ele usa todo dia."""
    if pode_decidir():
        return redirect(url_for("aprovacoes.listar"))
    return redirect(url_for("lancamentos.listar"))


@bp.route("/relatorios")
@login_required
def consolidado():
    repo = get_repo()
    ano, mes, inicio, fim = _periodo()
    unidade = request.args.get("unidade") or ""
    status = request.args.get("status") or ""

    itens = repo.lancamentos(
        inicio=inicio, fim=fim, unidade=unidade or None, status=status or None
    )
    return render_template(
        "relatorios/consolidado.html",
        fechamento=repo.fechamento(ano, mes),
        linhas=agrupa_por_funcionario(itens),
        unidades=repo.unidades(),
        ano=ano,
        mes=mes,
        unidade=unidade,
        status=status,
    )


@bp.route("/relatorios/csv")
@login_required
def consolidado_csv():
    repo = get_repo()
    ano, mes, inicio, fim = _periodo()
    unidade = request.args.get("unidade") or ""
    status = request.args.get("status") or ""
    itens = repo.lancamentos(
        inicio=inicio, fim=fim, unidade=unidade or None, status=status or None
    )

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow([
        "Data", "Prontuario", "Funcionario", "Unidade", "Entrada", "Saida",
        "Permanencia", "Almoco descontado", "Horas trabalhadas",
        "Horas excedidas", "Excedidas (decimal)",
        "Status", "HC solicitada", "HC status", "Lancado por", "Decidido por",
        "Parecer do gestor",
    ])
    for i in itens:
        escritor.writerow([
            i["data_br"], i["prontuario"], i["funcionario"], i["unidade"],
            format_duration(i["entrada_seg"]), format_duration(i["saida_seg"]),
            format_duration(i["permanencia_seg"]), format_duration(i["almoco_seg"]),
            format_duration(i["trabalhadas_seg"]), format_duration(i["excedidas_seg"]),
            str(horas_decimais(i["excedidas_seg"])).replace(".", ","),
            i["status"], "Sim" if i["hc_solicitada"] else "Nao", i["hc_status"],
            i["lancado_por"], i["decidido_por"], i["parecer"],
        ])

    nome = f"horas-extras-{ano}-{mes:02d}.csv"
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
