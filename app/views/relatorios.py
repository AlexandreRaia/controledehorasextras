"""Rota inicial e relatorio resumo (total de excedentes por funcionario)."""
import csv
import io

from flask import (
    Blueprint, Response, flash, redirect, render_template, request, url_for,
)

from .. import get_repo
from ..auth import login_required, pode_decidir
from ..periodos import meses_fechados, periodo
from ..utils import (
    agrupa_por_funcionario,
    format_duration,
    horas_decimais,
)

bp = Blueprint("relatorios", __name__)


def _periodo(avisos=None):
    return periodo(request.args, avisos)


# ----------------------------------------------------------------- resumo
SITUACOES = ("Pendente", "Aprovado", "Rejeitado")
# Qual subtotal do funcionario forma o "total" do resumo, conforme a situacao pedida.
CAMPO_DO_TOTAL = {
    "": "excedidas", "Aprovado": "aprovadas", "Pendente": "pendentes", "Rejeitado": "rejeitadas",
}


def _situacao_do_resumo():
    """Situacao cujas horas formam o total do resumo.

    Sem o parametro, so as aprovadas, que sao as que importam para a folha. "Todas" e
    uma escolha de proposito (valor vazio), e um valor desconhecido tambem cai em "Todas".
    """
    bruto = request.args.get("status")
    if bruto is None:
        return "Aprovado"
    return bruto if bruto in SITUACOES else ""


def _dados_do_resumo(avisos=None):
    """O que a tela e o CSV do resumo mostram: uma linha por funcionario com lancamentos.

    Os lancamentos vem de todas as situacoes, porque a coluna "aguardando decisao" precisa
    das pendentes mesmo quando o total e so das aprovadas; a situacao escolhida so decide
    qual subtotal vira o total.
    """
    repo = get_repo()
    ano, mes, inicio, fim, personalizado = _periodo(avisos)
    unidade = request.args.get("unidade") or ""
    prontuario = (request.args.get("prontuario") or "").strip()
    situacao = _situacao_do_resumo()

    itens = repo.lancamentos(
        inicio=inicio, fim=fim, prontuario=prontuario or None, unidade=unidade or None,
    )
    campo = CAMPO_DO_TOTAL[situacao]
    linhas = [
        {
            "funcionario": g["funcionario"], "prontuario": g["prontuario"],
            "unidade": g["unidade"], "total": g[campo], "pendente": g["pendentes"],
        }
        for g in agrupa_por_funcionario(itens)
    ]
    return {
        "repo": repo, "ano": ano, "mes": mes, "inicio": inicio, "fim": fim,
        "personalizado": personalizado, "unidade": unidade, "prontuario": prontuario,
        "situacao": situacao, "linhas": linhas,
        "total_geral": sum(l["total"] for l in linhas),
        "pendente_geral": sum(l["pendente"] for l in linhas),
    }


@bp.route("/relatorios/resumo")
@login_required
def resumo():
    avisos = []
    dados = _dados_do_resumo(avisos)
    for aviso in avisos:
        flash(aviso, "aviso")
    repo = dados.pop("repo")
    personalizado = dados["personalizado"]
    return render_template(
        "relatorios/resumo.html",
        fechamento=None if personalizado else repo.fechamento(dados["ano"], dados["mes"]),
        fechados_no_periodo=(
            meses_fechados(repo, dados["inicio"], dados["fim"]) if personalizado else []
        ),
        de=dados["inicio"] if personalizado else "",
        ate=dados["fim"] if personalizado else "",
        unidades=repo.unidades(),
        funcionarios=repo.funcionarios(),
        mostra_pendente=dados["situacao"] != "Pendente",
        **dados,
    )


@bp.route("/relatorios/resumo/csv")
@login_required
def resumo_csv():
    dados = _dados_do_resumo()
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow([
        "Funcionario", "Prontuario", "Unidade", "Situacao considerada",
        "Total horas excedentes", "Total (decimal)",
        "Aguardando decisao", "Aguardando (decimal)",
    ])
    for l in dados["linhas"]:
        escritor.writerow([
            l["funcionario"], l["prontuario"], l["unidade"], dados["situacao"] or "Todas",
            format_duration(l["total"]), str(horas_decimais(l["total"])).replace(".", ","),
            format_duration(l["pendente"]), str(horas_decimais(l["pendente"])).replace(".", ","),
        ])
    if dados["personalizado"]:
        nome = f"resumo-horas-extras-{dados['inicio']}_a_{dados['fim']}.csv"
    else:
        nome = f"resumo-horas-extras-{dados['ano']}-{dados['mes']:02d}.csv"
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@bp.route("/")
@login_required
def inicio():
    """A raiz leva cada perfil direto para a tela que ele usa todo dia."""
    if pode_decidir():
        return redirect(url_for("aprovacoes.listar"))
    return redirect(url_for("lancamentos.listar"))


@bp.route("/relatorios")
@bp.route("/relatorios/csv")
@login_required
def consolidado():
    """O relatorio detalhado virou a tela Lancamentos; links antigos seguem para la."""
    rota = "lancamentos.csv_lancamentos" if request.path.endswith("/csv") else "lancamentos.listar"
    return redirect(url_for(rota, **request.args.to_dict()))
