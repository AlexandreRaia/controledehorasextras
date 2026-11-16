"""Periodo de uma consulta (mes ou datas livres) e meses fechados que ele toca.

Usado por Lancamentos e pelo Resumo, para os dois lerem o filtro do mesmo jeito.
"""
from datetime import date

from .config import Config
from .utils import MESES, local_today, month_bounds, parse_date

LIMITE_PERIODO_DIAS = 366


def periodo(args, avisos=None):
    """(ano, mes, inicio, fim, personalizado) do pedido.

    Mes e ano valem por padrao. Se De e Ate forem duas datas validas, o periodo
    escolhido vale no lugar deles. Qualquer problema com as datas cai de volta no
    mes e ano, e o motivo vai para `avisos` (quem chama decide se mostra).
    """
    avisos = avisos if avisos is not None else []
    hoje = local_today(Config.TIMEZONE_OFFSET)
    try:
        ano = int(args.get("ano") or hoje.year)
        mes = int(args.get("mes") or hoje.month)
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    inicio, fim = month_bounds(ano, mes)

    bruto_de = (args.get("de") or "").strip()
    bruto_ate = (args.get("ate") or "").strip()
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


def meses_fechados(repo, inicio, fim):
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
