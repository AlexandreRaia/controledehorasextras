"""Conversoes de hora, data e pequenos auxiliares de formulario."""
import re
from datetime import date, datetime, timedelta, timezone

_HHMM = re.compile(r"^(\d{1,3})\s*[:hH]\s*(\d{1,2})$")
_ONLY_H = re.compile(r"^(\d{1,3})\s*[hH]?$")


def parse_duration(value):
    """Converte '8:30', '8h30', '8' ou segundos em segundos inteiros."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", ":")
    if not text:
        return None
    negative = text.startswith("-")
    text = text.lstrip("-")
    match = _HHMM.match(text)
    if match:
        horas, minutos = int(match.group(1)), int(match.group(2))
    else:
        match = _ONLY_H.match(text)
        if not match:
            try:
                return int(float(text))
            except ValueError:
                return None
        horas, minutos = int(match.group(1)), 0
    if minutos > 59:
        return None
    total = horas * 3600 + minutos * 60
    return -total if negative else total


def format_duration(seconds):
    """Converte segundos em 'H:MM'."""
    if seconds is None or seconds == "":
        return ""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    sinal = "-" if total < 0 else ""
    total = abs(total)
    return f"{sinal}{total // 3600}:{(total % 3600) // 60:02d}"


def horas_decimais(seconds):
    if not seconds:
        return 0.0
    return round(float(seconds) / 3600.0, 2)


def calcula_jornada(entrada_seg, saida_seg, jornada_padrao, almoco=0, hc_autorizada=False):
    """Permanencia, desconto do almoco, horas trabalhadas e excedentes.

    A permanencia e a diferenca entre saida e entrada, virando a meia-noite
    quando a saida e menor. Dela sai a hora de almoco, que nunca conta como
    excedente, salvo quando o gestor autoriza a hora corrida: ai o funcionario
    nao almocou e essa hora entra no excedente.

    O desconto nunca derruba a jornada abaixo do padrao, entao quem fica 8:30
    nao aparece devendo meia hora.
    """
    if entrada_seg is None or saida_seg is None:
        return None, None, None, None

    permanencia = saida_seg - entrada_seg
    if permanencia < 0:
        permanencia += 24 * 3600

    if hc_autorizada:
        desconto = 0
    else:
        desconto = max(0, min(almoco, permanencia - jornada_padrao))

    trabalhadas = permanencia - desconto
    excedidas = max(0, trabalhadas - jornada_padrao)
    return permanencia, desconto, trabalhadas, excedidas


def agrupa_por_funcionario(itens):
    """Agrupa lancamentos por funcionario e soma o subtotal de cada grupo.

    Devolve uma lista de grupos em ordem alfabetica, cada um com os dias
    ordenados por data e os totais do proprio grupo.
    """
    grupos = {}
    for item in itens:
        chave = item["prontuario"] or item["funcionario"]
        grupo = grupos.get(chave)
        if grupo is None:
            grupo = grupos[chave] = {
                "chave": chave,
                "funcionario": item["funcionario"] or chave,
                "prontuario": item["prontuario"],
                "unidade": item["unidade"],
                "itens": [],
                "dias": 0,
                "permanencia": 0,
                "almoco": 0,
                "trabalhadas": 0,
                "excedidas": 0,
                "aprovadas": 0,
                "pendentes": 0,
                "rejeitadas": 0,
                "hc_pedidas": 0,
                "hc_autorizadas": 0,
            }
        grupo["itens"].append(item)
        grupo["dias"] += 1
        grupo["permanencia"] += item.get("permanencia_seg") or 0
        grupo["almoco"] += item.get("almoco_seg") or 0
        grupo["trabalhadas"] += item.get("trabalhadas_seg") or 0
        excedente = item.get("excedidas_seg") or 0
        grupo["excedidas"] += excedente
        if item["status"] == "Aprovado":
            grupo["aprovadas"] += excedente
        elif item["status"] == "Rejeitado":
            grupo["rejeitadas"] += excedente
        else:
            grupo["pendentes"] += excedente
        if item["hc_solicitada"]:
            grupo["hc_pedidas"] += 1
        if item["hc_status"] == "Autorizada":
            grupo["hc_autorizadas"] += 1
        if not grupo["unidade"]:
            grupo["unidade"] = item["unidade"]

    ordenados = sorted(grupos.values(), key=lambda g: g["funcionario"].lower())
    for grupo in ordenados:
        grupo["itens"].sort(key=lambda i: i["data"] or "")
    return ordenados


def local_now(offset_hours=-3):
    return datetime.now(timezone.utc) + timedelta(hours=offset_hours)


def local_today(offset_hours=-3):
    return local_now(offset_hours).date()


def iso_now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value):
    """Aceita 'YYYY-MM-DD' ou 'DD/MM/YYYY' e devolve 'YYYY-MM-DD'."""
    if not value:
        return None
    text = str(value).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def format_date_br(value):
    iso = parse_date(value)
    if not iso:
        return ""
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def format_datetime_br(value, offset_hours=-3):
    if not value:
        return ""
    text = str(value).replace("Z", "+00:00")
    try:
        momento = datetime.fromisoformat(text)
    except ValueError:
        return format_date_br(value)
    if momento.tzinfo is not None:
        momento = momento.astimezone(timezone.utc) + timedelta(hours=offset_hours)
        momento = momento.replace(tzinfo=None)
    return momento.strftime("%d/%m/%Y %H:%M")


def month_bounds(ano, mes):
    inicio = date(ano, mes, 1)
    fim = date(ano + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)
    return inicio.isoformat(), fim.isoformat()


def select_value(cell):
    """Le o valor textual de um campo single select do Baserow."""
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def link_values(cell):
    """Le [{'id':..,'value':..}] de um campo de ligacao."""
    if not isinstance(cell, list):
        return []
    return [item.get("value") for item in cell if isinstance(item, dict)]


def link_ids(cell):
    if not isinstance(cell, list):
        return []
    return [item.get("id") for item in cell if isinstance(item, dict)]
