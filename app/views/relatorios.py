"""Rota inicial, consolidado mensal e exportacao em CSV."""
import csv
import io

from datetime import date

from flask import (
    Blueprint, Response, flash, redirect, render_template, request, url_for,
)

from .. import get_repo
from ..auth import login_required, pode_decidir
from ..config import Config
from ..utils import (
    agrupa_por_funcionario,
    format_duration,
    horas_decimais,
    local_today,
    month_bounds,
    MESES,
    parse_date,
)

bp = Blueprint("relatorios", __name__)


LIMITE_PERIODO_DIAS = 366


def _periodo(avisos=None):
    """(ano, mes, inicio, fim, personalizado) do pedido.

    Mes e ano valem por padrao. Se De e Ate forem duas datas validas, o periodo
    escolhido vale no lugar deles. Qualquer problema com as datas cai de volta no
    mes e ano, e o motivo vai para `avisos` (quem chama decide se mostra).
    """
    avisos = avisos if avisos is not None else []
    hoje = local_today(Config.TIMEZONE_OFFSET)
    try:
        ano = int(request.args.get("ano") or hoje.year)
        mes = int(request.args.get("mes") or hoje.month)
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    inicio, fim = month_bounds(ano, mes)

    bruto_de = (request.args.get("de") or "").strip()
    bruto_ate = (request.args.get("ate") or "").strip()
    if not bruto_de and not bruto_ate:
        return ano, mes, inicio, fim, False

    de, ate = parse_date(bruto_de), parse_date(bruto_ate)
    if not de or not ate:
        avisos.append("Informe as duas datas, De e Ate, para filtrar por periodo. "
                      "Usando o mes e o ano selecionados.")
    elif de > ate:
        avisos.append("A data inicial e maior que a final. "
                      "Usando o mes e o ano selecionados.")
    elif (date.fromisoformat(ate) - date.fromisoformat(de)).days + 1 > LIMITE_PERIODO_DIAS:
        avisos.append(f"O periodo maximo e de {LIMITE_PERIODO_DIAS} dias. "
                      "Usando o mes e o ano selecionados.")
    else:
        return ano, mes, de, ate, True
    return ano, mes, inicio, fim, False


def _meses_fechados(repo, inicio, fim):
    """Meses fechados que o periodo toca, ja com o rotulo para a faixa de aviso."""
    nomes = dict(MESES)
    atual = date.fromisoformat(inicio).replace(day=1)
    ultimo = date.fromisoformat(fim)
    fechados = []
    while atual <= ultimo:
        fechamento = repo.fechamento(atual.year, atual.month)
        if fechamento:
            fechados.append({**fechamento, "rotulo": f"{nomes[atual.month]}/{atual.year}"})
        atual = date(atual.year + (atual.month == 12), atual.month % 12 + 1, 1)
    return fechados


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
            _meses_fechados(repo, dados["inicio"], dados["fim"]) if personalizado else []
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
@login_required
def consolidado():
    repo = get_repo()
    avisos = []
    ano, mes, inicio, fim, personalizado = _periodo(avisos)
    for aviso in avisos:
        flash(aviso, "aviso")
    unidade = request.args.get("unidade") or ""
    status = request.args.get("status") or ""
    prontuario = (request.args.get("prontuario") or "").strip()

    itens = repo.lancamentos(
        inicio=inicio, fim=fim, prontuario=prontuario or None,
        unidade=unidade or None, status=status or None,
    )
    return render_template(
        "relatorios/consolidado.html",
        fechamento=None if personalizado else repo.fechamento(ano, mes),
        fechados_no_periodo=_meses_fechados(repo, inicio, fim) if personalizado else [],
        personalizado=personalizado,
        inicio=inicio,
        fim=fim,
        de=inicio if personalizado else "",
        ate=fim if personalizado else "",
        linhas=agrupa_por_funcionario(itens),
        unidades=repo.unidades(),
        funcionarios=repo.funcionarios(),
        ano=ano,
        mes=mes,
        unidade=unidade,
        status=status,
        prontuario=prontuario,
    )


@bp.route("/relatorios/csv")
@login_required
def consolidado_csv():
    repo = get_repo()
    ano, mes, inicio, fim, personalizado = _periodo()
    unidade = request.args.get("unidade") or ""
    status = request.args.get("status") or ""
    prontuario = (request.args.get("prontuario") or "").strip()
    itens = repo.lancamentos(
        inicio=inicio, fim=fim, prontuario=prontuario or None,
        unidade=unidade or None, status=status or None,
    )

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow([
        "Data", "Prontuario", "Funcionario", "Unidade", "Entrada", "Saida",
        "Permanencia", "Almoco descontado", "Horas trabalhadas",
        "Horas excedidas", "Excedidas (decimal)",
        "Status", "HC solicitada", "HC status", "Lancado por", "Decidido por",
        "Parecer do gestor", "Jornada (h)", "Plantao fora da escala",
        "Excedente calculado", "Ajustado pelo RH",
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
            i["jornada_horas"], "Sim" if i["fora_escala"] else "Nao",
            format_duration(i["excedidas_calc_seg"]), "Sim" if i["ajustado"] else "Nao",
        ])

    nome = (
        f"horas-extras-{inicio}_a_{fim}.csv" if personalizado
        else f"horas-extras-{ano}-{mes:02d}.csv"
    )
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
