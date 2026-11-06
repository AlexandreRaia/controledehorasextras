"""Manutencao de funcionarios, unidades e usuarios. Exclusivo do administrador.

As tres telas seguem o mesmo padrao: lista com filtro no topo, cadastrar e editar
em um modal (htmx), excluir so quando nada esta vinculado e inativar quando ha
vinculos. Cada cadastro define so o que e proprio dele; as rotas sao as mesmas.
"""
from urllib.parse import parse_qsl, urlparse

from flask import (
    Blueprint, abort, flash, make_response, redirect, render_template, request, url_for,
)
from werkzeug.datastructures import MultiDict

from .. import get_repo
from ..auth import PERFIL_ADMIN, PERFIS, hash_senha, perfil_required, usuario_atual
from ..utils import normaliza

bp = Blueprint("cadastros", __name__, url_prefix="/cadastros")


# ------------------------------------------------------------------ cadastros
class Cadastro:
    """O que muda de um cadastro para outro. O resto fica nas rotas abaixo."""

    chave = ""          # parte da URL e prefixo dos nomes das rotas
    singular = ""       # nas mensagens: "Funcionario"
    feminino = False    # "cadastrado" ou "cadastrada"

    def msg(self, participio):
        """msg("cadastrad") -> "Funcionario cadastrado." """
        return f"{self.singular} {participio}{'a' if self.feminino else 'o'}."

    # --- leitura
    def itens(self, repo):
        raise NotImplementedError

    def obter(self, repo, row_id):
        raise NotImplementedError

    def texto_busca(self, item):
        return item["nome"]

    # --- vinculos: o que impede excluir
    def vinculos(self, repo):
        return {}

    def chave_vinculo(self, item):
        return item["id"]

    def total(self, valor):
        return int(valor or 0)

    def decora(self, item, valor):
        """Campos extras para a lista, a partir do que `vinculos` devolveu."""

    def descreve_vinculos(self, item, valor):
        return f"{item['nome']} tem {self.total(valor)} registro(s) vinculado(s)."

    # --- filtros proprios (alem da busca e da situacao)
    def filtros(self, args):
        return {}

    def passa(self, item, filtros):
        return True

    def contexto_lista(self, repo):
        return {}

    # --- formulario
    def contexto_form(self, repo, item):
        return {}

    def valores(self, item):
        raise NotImplementedError

    def le_formulario(self, form, repo, row_id):
        """(dados, erros)"""
        raise NotImplementedError

    def criar(self, repo, dados):
        raise NotImplementedError

    def atualizar(self, repo, row_id, dados):
        raise NotImplementedError

    def excluir(self, repo, row_id):
        raise NotImplementedError

    def definir_ativo(self, repo, row_id, ativo):
        raise NotImplementedError

    # --- regras de excluir e inativar
    def erro_exclusao(self, repo, item, valor):
        if self.total(valor):
            return self.descreve_vinculos(item, valor) + " Inative em vez de excluir."
        return None

    def erro_situacao(self, repo, item, ativo):
        return None


class Funcionarios(Cadastro):
    chave = "funcionarios"
    singular = "Funcionario"

    def itens(self, repo):
        return repo.funcionarios()

    def obter(self, repo, row_id):
        return repo.funcionario(row_id)

    def texto_busca(self, item):
        return f"{item['nome']} {item['prontuario']} {item['cargo']} {item['telefone']}"

    def vinculos(self, repo):
        return repo.vinculos_funcionarios()

    def chave_vinculo(self, item):
        return item["prontuario"]

    def descreve_vinculos(self, item, valor):
        return f"{item['nome']} tem {self.total(valor)} lancamento(s) no historico."

    def filtros(self, args):
        return {"unidade": args.get("unidade") or ""}

    def passa(self, item, filtros):
        unidade = filtros["unidade"]
        if not unidade:
            return True
        if unidade == "sem":
            return not item["unidade_ids"]
        return unidade in [str(i) for i in item["unidade_ids"]]

    def contexto_lista(self, repo):
        return {"unidades": repo.unidades()}

    def contexto_form(self, repo, item):
        # Unidade inativa nao e oferecida, a menos que seja a que a pessoa ja tem.
        atuais = set(item["unidade_ids"]) if item else set()
        return {"unidades": [u for u in repo.unidades() if u["ativo"] or u["id"] in atuais]}

    def valores(self, item):
        if not item:
            return {"ativo": True, "jornada_horas": 8}
        return {
            "nome": item["nome"], "prontuario": item["prontuario"],
            "telefone": item["telefone"], "cargo": item["cargo"],
            "unidade_id": item["unidade_ids"][0] if item["unidade_ids"] else "",
            "jornada_horas": item["jornada_horas"], "ativo": item["ativo"],
        }

    def le_formulario(self, form, repo, row_id):
        dados = {
            "nome": (form.get("nome") or "").strip(),
            "prontuario": (form.get("prontuario") or "").strip(),
            "telefone": (form.get("telefone") or "").strip(),
            "cargo": (form.get("cargo") or "").strip(),
            "unidade_id": form.get("unidade_id") or None,
            "ativo": bool(form.get("ativo")),
            "jornada_horas": 12 if form.get("jornada_horas") == "12" else 8,
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
        return dados, erros

    def criar(self, repo, dados):
        repo.funcionario_criar(dados)

    def atualizar(self, repo, row_id, dados):
        repo.funcionario_atualizar(row_id, dados)

    def excluir(self, repo, row_id):
        repo.funcionario_excluir(row_id)

    def definir_ativo(self, repo, row_id, ativo):
        repo.funcionario_definir_ativo(row_id, ativo)


class Unidades(Cadastro):
    chave = "unidades"
    singular = "Unidade"
    feminino = True

    def itens(self, repo):
        return repo.unidades()

    def obter(self, repo, row_id):
        return repo.unidade(row_id)

    def vinculos(self, repo):
        return repo.vinculos_unidades()

    def total(self, valor):
        valor = valor or {}
        return valor.get("funcionarios", 0) + valor.get("lancamentos", 0)

    def decora(self, item, valor):
        item["n_funcionarios"] = (valor or {}).get("funcionarios", 0)

    def descreve_vinculos(self, item, valor):
        valor = valor or {}
        return (
            f"A unidade {item['nome']} tem {valor.get('funcionarios', 0)} funcionario(s) "
            f"e {valor.get('lancamentos', 0)} lancamento(s) vinculado(s)."
        )

    def valores(self, item):
        return {"ativo": True} if not item else {"nome": item["nome"], "ativo": item["ativo"]}

    def le_formulario(self, form, repo, row_id):
        dados = {"nome": (form.get("nome") or "").strip(), "ativo": bool(form.get("ativo"))}
        erros = []
        if not dados["nome"]:
            erros.append("Informe o nome da unidade.")
        elif any(
            normaliza(u["nome"]) == normaliza(dados["nome"]) and str(u["id"]) != str(row_id or "")
            for u in repo.unidades()
        ):
            erros.append(f"Ja existe uma unidade chamada {dados['nome']}.")
        return dados, erros

    def criar(self, repo, dados):
        repo.unidade_criar(dados["nome"], dados["ativo"])

    def atualizar(self, repo, row_id, dados):
        repo.unidade_atualizar(row_id, dados["nome"], dados["ativo"])

    def excluir(self, repo, row_id):
        repo.unidade_excluir(row_id)

    def definir_ativo(self, repo, row_id, ativo):
        repo.unidade_definir_ativo(row_id, ativo)


class Usuarios(Cadastro):
    chave = "usuarios"
    singular = "Usuario"

    def itens(self, repo):
        return repo.usuarios()

    def obter(self, repo, row_id):
        usuario = next((u for u in repo.usuarios() if u["id"] == row_id), None)
        if usuario is None:
            abort(404)
        return usuario

    def texto_busca(self, item):
        return f"{item['nome']} {item['login']} {item['perfil']}"

    def vinculos(self, repo):
        return repo.vinculos_usuarios()

    def chave_vinculo(self, item):
        # Lancamentos e fechamentos guardam o nome de quem fez, nao o id.
        return item["nome"]

    def descreve_vinculos(self, item, valor):
        return f"{item['nome']} tem {self.total(valor)} lancamento(s) ou fechamento(s) no historico."

    def filtros(self, args):
        return {"perfil": args.get("perfil") or ""}

    def passa(self, item, filtros):
        return not filtros["perfil"] or item["perfil"] == filtros["perfil"]

    def contexto_lista(self, repo):
        return {"perfis": PERFIS}

    def contexto_form(self, repo, item):
        return {"perfis": PERFIS}

    def valores(self, item):
        if not item:
            return {"ativo": True, "perfil": PERFIS[1]}
        return {"nome": item["nome"], "login": item["login"], "perfil": item["perfil"],
                "ativo": item["ativo"]}

    def le_formulario(self, form, repo, row_id):
        senha = form.get("senha") or ""
        dados = {
            "nome": (form.get("nome") or "").strip(),
            "login": (form.get("login") or "").strip(),
            "perfil": form.get("perfil") or "",
            "ativo": bool(form.get("ativo")),
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
                erros.append("Voce nao pode remover o proprio acesso de administrador.")
        if senha:
            dados["hash"] = hash_senha(senha)
        return dados, erros

    def criar(self, repo, dados):
        repo.usuario_criar(dados)

    def atualizar(self, repo, row_id, dados):
        repo.usuario_atualizar(row_id, dados)

    def excluir(self, repo, row_id):
        repo.usuario_excluir(row_id)

    def definir_ativo(self, repo, row_id, ativo):
        repo.usuario_definir_ativo(row_id, ativo)

    @staticmethod
    def _e_o_ultimo_admin(repo, item):
        if item["perfil"] != PERFIL_ADMIN or not item["ativo"]:
            return False
        return not any(
            u["perfil"] == PERFIL_ADMIN and u["ativo"] and u["id"] != item["id"]
            for u in repo.usuarios()
        )

    def erro_exclusao(self, repo, item, valor):
        atual = usuario_atual()
        if atual and str(atual["id"]) == str(item["id"]):
            return "Voce nao pode excluir o proprio usuario."
        if self._e_o_ultimo_admin(repo, item):
            return "Mantenha ao menos um administrador ativo."
        return super().erro_exclusao(repo, item, valor)

    def erro_situacao(self, repo, item, ativo):
        if ativo:
            return None
        atual = usuario_atual()
        if atual and str(atual["id"]) == str(item["id"]):
            return "Voce nao pode inativar o proprio usuario."
        if self._e_o_ultimo_admin(repo, item):
            return "Mantenha ao menos um administrador ativo."
        return None


# ----------------------------------------------------------------- mecanismo
def _htmx():
    """A chamada vem do htmx (modal e lista), e nao de uma navegacao comum."""
    return request.headers.get("HX-Request") == "true"


def _voltar(chave):
    """Lista de onde o admin veio, com a busca e os filtros. So aceita esta tela."""
    destino = request.values.get("voltar") or ""
    if destino.startswith(f"/cadastros/{chave}") and not destino.startswith("//"):
        return destino
    return url_for(f"cadastros.{chave}")


def _contexto_lista(cad, args):
    """Tudo o que a lista precisa para a busca e os filtros recebidos."""
    repo = get_repo()
    itens = cad.itens(repo)
    vinculos = cad.vinculos(repo)
    q = normaliza((args.get("q") or "").strip())
    situacao = args.get("situacao") or ""
    filtros = cad.filtros(args)

    visiveis = []
    for original in itens:
        item = dict(original)
        valor = vinculos.get(cad.chave_vinculo(item))
        item["vinculos"] = cad.total(valor)
        cad.decora(item, valor)
        if q and q not in normaliza(cad.texto_busca(item)):
            continue
        if situacao == "ativos" and not item["ativo"]:
            continue
        if situacao == "inativos" and item["ativo"]:
            continue
        if not cad.passa(item, filtros):
            continue
        visiveis.append(item)

    atual = usuario_atual()
    return {
        "itens": visiveis,
        "total": len(itens),
        "q": args.get("q") or "",
        "situacao": situacao,
        "filtros": filtros,
        "atual_id": atual["id"] if atual else None,
        **cad.contexto_lista(repo),
    }


def _registra(cad):
    chave = cad.chave
    modelo_pagina = f"cadastros/{chave}.html"
    modelo_lista = f"cadastros/_{chave}_lista.html"

    def lista_atualizada(fechar_modal):
        """Sem JavaScript volta para a lista. Com htmx devolve so a lista, no lugar
        da antiga, com os mesmos filtros; depois de salvar manda fechar o modal."""
        destino = _voltar(chave)
        if not _htmx():
            return redirect(destino)
        args = MultiDict(parse_qsl(urlparse(destino).query))
        resposta = make_response(render_template(
            modelo_lista, cad=cad, voltar=destino, avisos_na_lista=True,
            **_contexto_lista(cad, args),
        ))
        resposta.headers["HX-Retarget"] = "#lista"
        resposta.headers["HX-Reswap"] = "outerHTML"
        if fechar_modal:
            resposta.headers["HX-Trigger"] = "modal-fechar"
        return resposta

    def formulario(item, valores, acao):
        """So o miolo dentro do modal, ou a pagina inteira sem JavaScript."""
        modal = _htmx()
        contexto = dict(
            cad=cad, item=item, form=valores, acao=acao, modal=modal,
            voltar=_voltar(chave), **cad.contexto_form(get_repo(), item),
        )
        if modal:
            return render_template(f"cadastros/_{chave}_form.html", **contexto)
        return render_template(
            "cadastros/form.html", modelo_form=f"cadastros/_{chave}_form.html", **contexto
        )

    def listar():
        contexto = _contexto_lista(cad, request.args)
        return render_template(
            modelo_lista if _htmx() else modelo_pagina,
            cad=cad, voltar=request.full_path.rstrip("?"), **contexto,
        )

    def novo():
        repo = get_repo()
        acao = url_for(f"cadastros.{chave}_novo")
        if request.method == "POST":
            dados, erros = cad.le_formulario(request.form, repo, None)
            if erros:
                for erro in erros:
                    flash(erro, "erro")
                return formulario(None, request.form, acao)
            cad.criar(repo, dados)
            flash(cad.msg("cadastrad"), "ok")
            return lista_atualizada(fechar_modal=True)
        return formulario(None, cad.valores(None), acao)

    def editar(row_id):
        repo = get_repo()
        item = cad.obter(repo, row_id)
        acao = url_for(f"cadastros.{chave}_editar", row_id=row_id)
        if request.method == "POST":
            dados, erros = cad.le_formulario(request.form, repo, row_id)
            if erros:
                for erro in erros:
                    flash(erro, "erro")
                return formulario(item, request.form, acao)
            cad.atualizar(repo, row_id, dados)
            flash(cad.msg("atualizad"), "ok")
            return lista_atualizada(fechar_modal=True)
        return formulario(item, cad.valores(item), acao)

    def excluir(row_id):
        repo = get_repo()
        item = cad.obter(repo, row_id)
        valor = cad.vinculos(repo).get(cad.chave_vinculo(item))
        erro = cad.erro_exclusao(repo, item, valor)
        if erro:
            flash(erro, "erro")
        else:
            cad.excluir(repo, row_id)
            flash(cad.msg("excluid"), "ok")
        return lista_atualizada(fechar_modal=False)

    def situacao(row_id):
        repo = get_repo()
        item = cad.obter(repo, row_id)
        ativo = request.form.get("ativo") == "1"
        erro = cad.erro_situacao(repo, item, ativo)
        if erro:
            flash(erro, "erro")
        else:
            cad.definir_ativo(repo, row_id, ativo)
            flash(cad.msg("reativad" if ativo else "inativad"), "ok")
        return lista_atualizada(fechar_modal=False)

    protegido = perfil_required(PERFIL_ADMIN)
    regras = (
        (f"/{chave}", chave, listar, ["GET"]),
        (f"/{chave}/novo", f"{chave}_novo", novo, ["GET", "POST"]),
        (f"/{chave}/<int:row_id>/editar", f"{chave}_editar", editar, ["GET", "POST"]),
        (f"/{chave}/<int:row_id>/excluir", f"{chave}_excluir", excluir, ["POST"]),
        (f"/{chave}/<int:row_id>/situacao", f"{chave}_situacao", situacao, ["POST"]),
    )
    for caminho, endpoint, funcao, metodos in regras:
        bp.add_url_rule(caminho, endpoint=endpoint, view_func=protegido(funcao), methods=metodos)


for _cadastro in (Funcionarios(), Unidades(), Usuarios()):
    _registra(_cadastro)
