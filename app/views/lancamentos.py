"""Lancamento de horas. Exclusivo do RH; os demais perfis so consultam."""
import csv
import io
from urllib.parse import parse_qsl, urlparse

from flask import (
    Blueprint, Response, flash, make_response, redirect, render_template, request,
    url_for,
)
from werkzeug.datastructures import MultiDict

from .. import get_repo
from ..auth import PERFIL_RH, login_required, perfil_required, usuario_atual
from ..config import Config
from ..periodos import meses_fechados, periodo
from .. import schema as S
from ..utils import (
    agrupa_por_funcionario,
    format_duration,
    horas_decimais,
    iso_now_utc,
    local_today,
    parse_date,
    parse_duration,
)

bp = Blueprint("lancamentos", __name__, url_prefix="/lancamentos")

STATUS_PENDENTE = "Pendente"
HC_NAO_SOLICITADA = "Nao solicitada"
HC_PENDENTE = "Pendente"
MSG_FECHADO = "O mes desta data ja foi fechado. Fale com o administrador."


LIMITE_EXCEDENTE_SEG = 20 * 3600
# Acima disto a permanencia pode ser erro de digitacao: o sistema so alerta.
PERMANENCIA_A_ALERTAR_SEG = 20 * 3600


def alerta_longa(permanencia):
    flash(
        f"Atencao: permanencia de {format_duration(permanencia)}, acima de "
        f"{PERMANENCIA_A_ALERTAR_SEG // 3600} horas. Confira entrada e saida.",
        "aviso",
    )


def _le_excedente(bruto, erros):
    """Excedente digitado em H:MM (aceita sinal de menos), ou None se em branco."""
    texto = (bruto or "").strip()
    if not texto:
        return None
    valor = parse_duration(texto)
    if valor is None:
        erros.append("Excedente no formato H:MM; para horas negativas use -0:30.")
    elif abs(valor) > LIMITE_EXCEDENTE_SEG:
        # So alerta: um plantao longo pode ter excedente real acima de 20 horas.
        flash(
            f"Atencao: excedente de {format_duration(valor)}, acima de "
            f"{LIMITE_EXCEDENTE_SEG // 3600} horas. Confira o valor digitado.",
            "aviso",
        )
    return valor


def _monta_payload(form, funcionario):
    """Valida o formulario e devolve (payload, erros)."""
    erros = []
    data_iso = parse_date(form.get("data"))
    if not data_iso:
        erros.append("Informe a data do lancamento.")

    entrada = parse_duration(form.get("entrada"))
    saida = parse_duration(form.get("saida"))
    if entrada is None:
        erros.append("Informe a entrada no formato H:MM.")
    if saida is None:
        erros.append("Informe a saida no formato H:MM.")

    # Quem nao tem hora de almoco a descontar nao tem hora corrida a pedir.
    # A hora corrida pedida ja conta no excedente; se o gestor negar, o calculo
    # e refeito com o almoco descontado.
    jornada, almoco = Config.parametros_jornada(funcionario["jornada_horas"])
    hc = bool(form.get("hc_solicitada")) and almoco > 0
    plantonista = funcionario["jornada_horas"] == Config.JORNADA_PLANTAO_HORAS
    fora_escala = plantonista and bool(form.get("fora_escala"))
    permanencia, _, trabalhadas, excedidas = Config.calcula(
        funcionario["jornada_horas"], entrada, saida,
        hc_autorizada=hc, fora_escala=fora_escala,
    )
    # Permanencia muito longa e so alerta, nunca bloqueio: pode ser erro de
    # digitacao, mas tambem um plantao real. O lancamento e gravado e o alerta
    # aparece depois de salvar.
    if permanencia is not None and permanencia > PERMANENCIA_A_ALERTAR_SEG:
        alerta_longa(permanencia)

    obs = (form.get("obs_rh") or "").strip()

    # O RH pode digitar o excedente no lugar do calculado, inclusive negativo.
    # Valor igual ao calculado nao e ajuste; ajuste exige o motivo na observacao.
    manual = _le_excedente(form.get("excedente"), erros)
    if manual is not None and excedidas is not None and manual == excedidas:
        manual = None
    if manual is not None:
        if not obs:
            erros.append("Informe o motivo do ajuste na Observacao do RH.")
        excedidas = manual
    usuario = usuario_atual()
    payload = {
        S.F["lanc_data"]: data_iso,
        S.F["lanc_prontuario"]: funcionario["prontuario"],
        S.F["lanc_funcionario"]: funcionario["id"],
        S.F["lanc_entrada"]: entrada,
        S.F["lanc_saida"]: saida,
        S.F["lanc_excedidas"]: excedidas,
        S.F["lanc_excedidas_manual"]: manual,
        S.F["lanc_unidade"]: funcionario["unidade"],
        S.F["lanc_fora_escala"]: fora_escala,
        S.F["lanc_obs_rh"]: obs,
        S.F["lanc_hc_solicitada"]: hc,
        S.F["lanc_lancado_por"]: usuario["nome"] if usuario else "",
        S.F["lanc_lancado_em"]: iso_now_utc(),
    }
    return payload, erros, trabalhadas, excedidas


def _htmx():
    """A chamada vem do htmx (modal), e nao de uma navegacao comum."""
    return request.headers.get("HX-Request") == "true"


def _voltar():
    """Lista de onde o RH veio, com os filtros. So aceita caminhos desta tela."""
    destino = request.values.get("voltar") or ""
    if destino.startswith("/lancamentos") and not destino.startswith("//"):
        return destino
    return url_for("lancamentos.listar")


def _filtros(args, avisos=None):
    """Filtros da tela, iguais para a lista, o modal e o CSV."""
    ano, mes, inicio, fim, personalizado = periodo(args, avisos)
    return {
        "ano": ano, "mes": mes, "inicio": inicio, "fim": fim,
        "personalizado": personalizado,
        "de": inicio if personalizado else "",
        "ate": fim if personalizado else "",
        "unidade": args.get("unidade") or "",
        "prontuario": (args.get("prontuario") or "").strip(),
        "status": args.get("status") or "",
    }


def _busca(repo, f):
    return repo.lancamentos(
        inicio=f["inicio"], fim=f["fim"], prontuario=f["prontuario"] or None,
        unidade=f["unidade"] or None, status=f["status"] or None,
    )


def _contexto_lista(args, avisos=None):
    """Tudo o que a lista de lancamentos precisa para um periodo e filtros."""
    repo = get_repo()
    f = _filtros(args, avisos)
    itens = _busca(repo, f)
    personalizado = f["personalizado"]
    fechados = meses_fechados(repo, f["inicio"], f["fim"])
    fechados_em = {(x["ano"], x["mes"]) for x in fechados}
    for i in itens:
        i["fechado"] = (int(i["data"][:4]), int(i["data"][5:7])) in fechados_em
    return {
        **f,
        "fechamento": None if personalizado else repo.fechamento(f["ano"], f["mes"]),
        "fechados_no_periodo": fechados if personalizado else [],
        "grupos": agrupa_por_funcionario(itens),
        "itens": itens,
        "funcionarios": repo.funcionarios(),
        "unidades": repo.unidades(),
        "total_excedido": sum(i["excedidas_seg"] or 0 for i in itens),
    }


@bp.route("/")
@login_required
def listar():
    avisos = []
    contexto = _contexto_lista(request.args, avisos)
    for aviso in avisos:
        flash(aviso, "aviso")
    return render_template(
        "lancamentos/listar.html", voltar=request.full_path, **contexto
    )


@bp.route("/csv")
@login_required
def csv_lancamentos():
    """Os mesmos lancamentos da tela, com os mesmos filtros, em CSV."""
    f = _filtros(request.args)
    itens = _busca(get_repo(), f)
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
        f"horas-extras-{f['inicio']}_a_{f['fim']}.csv" if f["personalizado"]
        else f"horas-extras-{f['ano']}-{f['mes']:02d}.csv"
    )
    return Response(
        buffer.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


def _form(**contexto):
    """O formulario: so o miolo dentro do modal, ou a pagina inteira sem JavaScript."""
    modal = _htmx()
    modelo = "lancamentos/_form.html" if modal else "lancamentos/form.html"
    return render_template(modelo, modal=modal, voltar=_voltar(), **contexto)


def _aviso_no_modal(texto):
    return render_template("lancamentos/_modal_aviso.html", texto=texto)


def _depois_de_salvar():
    """Sem JavaScript volta para a lista. No modal devolve so a lista atualizada,
    no lugar da antiga, e manda fechar o modal: nada de recarregar a pagina."""
    destino = _voltar()
    if not _htmx():
        return redirect(destino)
    args = MultiDict(parse_qsl(urlparse(destino).query))
    resposta = make_response(render_template(
        "lancamentos/_lista.html", voltar=destino, avisos_na_lista=True,
        **_contexto_lista(args),
    ))
    resposta.headers["HX-Retarget"] = "#lista"
    resposta.headers["HX-Reswap"] = "outerHTML"
    resposta.headers["HX-Trigger"] = "modal-fechar"
    return resposta


@bp.route("/novo", methods=["GET", "POST"])
@perfil_required(PERFIL_RH)
def novo():
    repo = get_repo()
    funcionarios = repo.funcionarios(somente_ativos=True)
    hoje = local_today(Config.TIMEZONE_OFFSET).isoformat()
    acao = url_for("lancamentos.novo")

    if request.method == "POST":
        funcionario = _funcionario_do_form(repo, request.form)
        if not funcionario:
            flash("Selecione um funcionario valido.", "erro")
            return _form(
                funcionarios=funcionarios, item=None, hoje=hoje,
                form=request.form, acao=acao,
            )

        payload, erros, trabalhadas, excedidas = _monta_payload(
            request.form, funcionario
        )
        if not erros and repo.mes_fechado_data(payload[S.F["lanc_data"]]):
            erros.append(MSG_FECHADO)
        duplicado = None
        if not erros:
            duplicado = repo.existe_lancamento(
                funcionario["prontuario"], payload[S.F["lanc_data"]]
            )
            if duplicado:
                erros.append(
                    "Ja existe lancamento para este funcionario nesta data."
                )
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return _form(
                funcionarios=funcionarios, item=None, hoje=hoje,
                form=request.form, acao=acao,
            )

        payload[S.F["lanc_status"]] = STATUS_PENDENTE
        payload[S.F["lanc_hc_status"]] = (
            HC_PENDENTE if payload[S.F["lanc_hc_solicitada"]] else HC_NAO_SOLICITADA
        )
        repo.lancamento_criar(payload)
        flash(
            f"Lancamento registrado. Horas trabalhadas {format_duration(trabalhadas)}, "
            f"excedentes {format_duration(excedidas)}.",
            "ok",
        )
        return _depois_de_salvar()

    return _form(funcionarios=funcionarios, item=None, hoje=hoje, form={}, acao=acao)


@bp.route("/<int:row_id>/editar", methods=["GET", "POST"])
@perfil_required(PERFIL_RH)
def editar(row_id):
    repo = get_repo()
    item = repo.lancamento(row_id)
    if repo.mes_fechado_data(item["data"]):
        if _htmx():
            return _aviso_no_modal(MSG_FECHADO)
        flash(MSG_FECHADO, "erro")
        return redirect(_voltar())
    decidido = _ja_decidido(item)
    acao = url_for("lancamentos.editar", row_id=row_id)

    funcionarios = repo.funcionarios(somente_ativos=True)
    if request.method == "POST":
        funcionario = _funcionario_do_form(repo, request.form)
        if not funcionario:
            flash("Selecione um funcionario valido.", "erro")
            return _form(
                funcionarios=funcionarios, item=item, hoje=item["data"],
                form=request.form, decidido=decidido, acao=acao,
            )

        payload, erros, trabalhadas, excedidas = _monta_payload(
            request.form, funcionario
        )
        if not erros and repo.mes_fechado_data(payload[S.F["lanc_data"]]):
            erros.append(MSG_FECHADO)
        if not erros:
            duplicado = repo.existe_lancamento(
                funcionario["prontuario"], payload[S.F["lanc_data"]], ignorar_id=row_id
            )
            if duplicado:
                erros.append("Ja existe outro lancamento para este funcionario nesta data.")
        if erros:
            for erro in erros:
                flash(erro, "erro")
            return _form(
                funcionarios=funcionarios, item=item, hoje=item["data"],
                form=request.form, decidido=decidido, acao=acao,
            )

        # O RH nunca decide: editar devolve o lancamento ao gestor, entao a
        # unica situacao que ele grava aqui e Pendente, com a decisao zerada.
        payload[S.F["lanc_hc_status"]] = (
            HC_PENDENTE if payload[S.F["lanc_hc_solicitada"]] else HC_NAO_SOLICITADA
        )
        payload[S.F["lanc_status"]] = STATUS_PENDENTE
        payload[S.F["lanc_parecer"]] = ""
        payload[S.F["lanc_decidido_por"]] = ""
        payload[S.F["lanc_decidido_em"]] = None
        repo.lancamento_atualizar(row_id, payload)
        flash(
            f"Lancamento atualizado. Excedentes {format_duration(excedidas)}."
            + (" Ele voltou para nova decisao do gestor." if decidido else ""),
            "ok",
        )
        return _depois_de_salvar()

    form = {
        "data": item["data"],
        "funcionario_id": item["funcionario_ids"][0] if item["funcionario_ids"] else "",
        "entrada": format_duration(item["entrada_seg"]),
        "saida": format_duration(item["saida_seg"]),
        "obs_rh": item["obs_rh"],
        "hc_solicitada": item["hc_solicitada"],
        "fora_escala": item["fora_escala"],
        "excedente": format_duration(item["excedidas_seg"]) if item["ajustado"] else "",
    }
    return _form(
        funcionarios=funcionarios, item=item, hoje=item["data"], form=form,
        decidido=decidido, acao=acao,
    )


@bp.route("/<int:row_id>/excluir", methods=["POST"])
@perfil_required(PERFIL_RH)
def excluir(row_id):
    repo = get_repo()
    item = repo.lancamento(row_id)
    if repo.mes_fechado_data(item["data"]):
        flash(MSG_FECHADO, "erro")
    else:
        repo.lancamento_excluir(row_id)
        flash("Lancamento excluido.", "ok")
    return redirect(_voltar())


def _ja_decidido(item):
    """O gestor ja decidiu as horas ou a hora corrida deste lancamento."""
    return item["status"] != STATUS_PENDENTE or item["hc_status"] in ("Autorizada", "Negada")


def _funcionario_do_form(repo, form):
    bruto = form.get("funcionario_id")
    if not bruto:
        return None
    try:
        return repo.funcionario(int(bruto))
    except (ValueError, TypeError):
        return None
