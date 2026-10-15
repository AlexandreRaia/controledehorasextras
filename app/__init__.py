"""Fabrica da aplicacao Flask de Controle de Horas Extras."""
import logging

from urllib.parse import urlparse

from flask import Flask, flash, redirect, render_template, request, url_for

from .auth import (
    pode_cadastrar,
    pode_decidir,
    pode_fechar,
    pode_lancar,
    pode_reabrir,
    perfil_atual,
    usuario_atual,
)
from .db import DBError
from .config import Config
from .repo import MesFechado, Repo
from .utils import (
    format_date_br,
    format_datetime_br,
    format_duration,
    horas_decimais,
    ident,
    MESES,
)

_repo = None


def get_repo():
    """Cria o acesso ao banco na primeira chamada e reaproveita depois."""
    global _repo
    if _repo is None:
        _repo = Repo(Config)
    return _repo


def set_repo(repo):
    """Injeta um acesso a dados pronto. Usado pelos testes."""
    global _repo
    _repo = repo


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    logging.basicConfig(level=logging.INFO)

    from .views import (
        aprovacoes, auth as auth_views, cadastros, fechamento, lancamentos, relatorios,
    )

    app.register_blueprint(auth_views.bp)
    app.register_blueprint(lancamentos.bp)
    app.register_blueprint(aprovacoes.bp)
    app.register_blueprint(cadastros.bp)
    app.register_blueprint(relatorios.bp)
    app.register_blueprint(fechamento.bp)

    app.jinja_env.filters["dur"] = format_duration
    app.jinja_env.filters["data_br"] = format_date_br
    app.jinja_env.filters["datahora_br"] = format_datetime_br
    app.jinja_env.filters["hdec"] = horas_decimais
    app.jinja_env.filters["ident"] = ident
    app.jinja_env.globals["MESES"] = MESES

    @app.context_processor
    def injeta_contexto():
        return {
            "usuario": usuario_atual(),
            "perfil": perfil_atual(),
            "pode_lancar": pode_lancar(),
            "pode_decidir": pode_decidir(),
            "pode_cadastrar": pode_cadastrar(),
            "pode_fechar": pode_fechar(),
            "pode_reabrir": pode_reabrir(),
            "jornada_horas": app.config["JORNADA_PADRAO_SEGUNDOS"] // 3600,
            "almoco_a_partir_horas": app.config["ALMOCO_A_PARTIR_SEGUNDOS"] // 3600,
        }

    @app.errorhandler(403)
    def sem_permissao(_erro):
        return render_template(
            "erro.html",
            titulo="Acesso negado",
            mensagem="Seu perfil nao tem permissao para esta operacao.",
        ), 403

    @app.errorhandler(404)
    def nao_encontrado(_erro):
        return render_template(
            "erro.html",
            titulo="Pagina nao encontrada",
            mensagem="O endereco acessado nao existe.",
        ), 404

    @app.errorhandler(MesFechado)
    def mes_fechado(erro):
        """Rede de seguranca: nenhuma gravacao passa por um mes fechado."""
        flash(f"{erro} Fale com o administrador para reabri-lo.", "erro")
        origem = request.referrer
        if origem and urlparse(origem).netloc == request.host:
            return redirect(origem)
        return redirect(url_for("lancamentos.listar"))

    @app.errorhandler(DBError)
    def erro_banco(erro):
        app.logger.error("Erro no banco: %s", erro)
        return render_template(
            "erro.html",
            titulo="Falha no banco de dados",
            mensagem="Nao foi possivel concluir a operacao no banco de dados.",
            detalhe="Confira a DATABASE_URL no arquivo .env e se o PostgreSQL esta no ar.",
        ), 502

    return app
