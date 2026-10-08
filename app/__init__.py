"""Fabrica da aplicacao Flask de Controle de Horas Extras."""
import logging

from flask import Flask, render_template

from .auth import (
    pode_cadastrar,
    pode_decidir,
    pode_lancar,
    perfil_atual,
    usuario_atual,
)
from .baserow import BaserowError
from .config import Config
from .repo import Repo
from .utils import format_date_br, format_datetime_br, format_duration, horas_decimais

_repo = None
_repo_erro = None


def get_repo():
    """Cria o acesso ao Baserow na primeira chamada e reaproveita depois."""
    global _repo, _repo_erro
    if _repo is None:
        try:
            _repo = Repo(Config)
            _repo_erro = None
        except BaserowError as exc:
            _repo_erro = str(exc)
            raise
    return _repo


def set_repo(repo):
    """Injeta um acesso a dados pronto. Usado pelos testes."""
    global _repo, _repo_erro
    _repo = repo
    _repo_erro = None


def reset_repo():
    global _repo, _repo_erro
    _repo = None
    _repo_erro = None


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    logging.basicConfig(level=logging.INFO)

    from .views import aprovacoes, auth as auth_views, cadastros, lancamentos, relatorios

    app.register_blueprint(auth_views.bp)
    app.register_blueprint(lancamentos.bp)
    app.register_blueprint(aprovacoes.bp)
    app.register_blueprint(cadastros.bp)
    app.register_blueprint(relatorios.bp)

    app.jinja_env.filters["dur"] = format_duration
    app.jinja_env.filters["data_br"] = format_date_br
    app.jinja_env.filters["datahora_br"] = format_datetime_br
    app.jinja_env.filters["hdec"] = horas_decimais

    @app.context_processor
    def injeta_contexto():
        return {
            "usuario": usuario_atual(),
            "perfil": perfil_atual(),
            "pode_lancar": pode_lancar(),
            "pode_decidir": pode_decidir(),
            "pode_cadastrar": pode_cadastrar(),
            "jornada_horas": app.config["JORNADA_PADRAO_SEGUNDOS"] // 3600,
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

    @app.errorhandler(BaserowError)
    def erro_baserow(erro):
        return render_template(
            "erro.html",
            titulo="Falha na conexao com o Baserow",
            mensagem=str(erro),
            detalhe="Confira BASEROW_URL, BASEROW_EMAIL, BASEROW_PASSWORD e os IDs "
                    "das tabelas no arquivo .env.",
        ), 502

    return app
