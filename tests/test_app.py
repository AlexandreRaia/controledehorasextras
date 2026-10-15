"""Testes do calculo de horas e das regras de permissao, sem tocar no banco."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, set_repo  # noqa: E402
from app import schema as S  # noqa: E402
from app.auth import hash_senha  # noqa: E402
from app.config import Config  # noqa: E402
from app.repo import MesFechado, Repo  # noqa: E402
from app.utils import (  # noqa: E402
    agrupa_por_funcionario,
    calcula_jornada,
    format_duration,
    ident,
    parse_duration,
)


# ---------------------------------------------------------------- calculo
class TestCalculo(unittest.TestCase):
    def test_parse_duration_aceita_varios_formatos(self):
        self.assertEqual(parse_duration("8:00"), 8 * 3600)
        self.assertEqual(parse_duration("19:30"), 19 * 3600 + 1800)
        self.assertEqual(parse_duration("8h30"), 8 * 3600 + 1800)
        self.assertEqual(parse_duration("8"), 8 * 3600)
        self.assertEqual(parse_duration(28800), 28800)
        self.assertIsNone(parse_duration(""))
        self.assertIsNone(parse_duration("8:99"))

    def test_format_duration(self):
        self.assertEqual(format_duration(8 * 3600), "8:00")
        self.assertEqual(format_duration(11 * 3600 + 1800), "11:30")
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(None), "")

    def jornada(self, entrada, saida, hc=False):
        return calcula_jornada(
            parse_duration(entrada), parse_duration(saida), 8 * 3600, 3600,
            hc_autorizada=hc, almoco_a_partir=6 * 3600,
        )

    def test_almoco_sai_do_excedente(self):
        perm, almoco, trab, exced = self.jornada("8:00", "19:30")
        self.assertEqual(format_duration(perm), "11:30")
        self.assertEqual(format_duration(almoco), "1:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(format_duration(exced), "2:30")

    def test_trabalhadas_mostra_so_a_jornada_normal(self):
        # 8:00 as 19:00: permanencia 11h, trabalhadas 8h, 2h sem HC e 3h com HC.
        perm, _, trab, exced = self.jornada("8:00", "19:00")
        self.assertEqual(format_duration(perm), "11:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(format_duration(exced), "2:00")
        perm, _, trab, exced = self.jornada("8:00", "19:00", hc=True)
        self.assertEqual(format_duration(perm), "11:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(format_duration(exced), "3:00")

    def test_hora_corrida_devolve_a_hora_do_almoco(self):
        _, almoco, trab, exced = self.jornada("8:00", "19:30", hc=True)
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(format_duration(exced), "3:30")

    def test_dia_curto_fica_com_excedente_negativo(self):
        # 10:00 as 17:00: permanencia 7h, almoco 1h, 6h trabalhadas, devendo 2h.
        perm, almoco, trab, exced = self.jornada("10:00", "17:00")
        self.assertEqual(format_duration(perm), "7:00")
        self.assertEqual(format_duration(almoco), "1:00")
        self.assertEqual(format_duration(trab), "6:00")
        self.assertEqual(format_duration(exced), "-2:00")
        # Com hora corrida ele nao almocou: 7h trabalhadas, devendo 1h.
        perm, almoco, trab, exced = self.jornada("10:00", "17:00", hc=True)
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "7:00")
        self.assertEqual(format_duration(exced), "-1:00")

    def test_oito_e_meia_de_permanencia_fica_meia_hora_devendo(self):
        _, almoco, trab, exced = self.jornada("8:00", "16:30")
        self.assertEqual(format_duration(almoco), "1:00")
        self.assertEqual(format_duration(trab), "7:30")
        self.assertEqual(format_duration(exced), "-0:30")
        # Com hora corrida o almoco volta e sobra meia hora.
        _, _, _, exced_hc = self.jornada("8:00", "16:30", hc=True)
        self.assertEqual(format_duration(exced_hc), "0:30")

    def test_almoco_so_e_descontado_acima_de_6_horas(self):
        # Exatamente 6h de permanencia nao desconta; 6h01 desconta.
        _, almoco, trab, exced = self.jornada("8:00", "14:00")
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(exced), "-2:00")
        _, almoco, _, _ = self.jornada("8:00", "14:01")
        self.assertEqual(format_duration(almoco), "1:00")

    def test_meio_periodo_nao_desconta_almoco_e_fica_devendo(self):
        _, almoco, trab, exced = self.jornada("8:00", "12:00")
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "4:00")
        self.assertEqual(format_duration(exced), "-4:00")

    def plantao(self, entrada, saida, fora_escala=False):
        # Plantonista 12x36: jornada de 12 horas e nenhum almoco a descontar.
        jornada, almoco = Config.parametros_jornada(12)
        return calcula_jornada(
            parse_duration(entrada), parse_duration(saida), jornada, almoco,
            fora_escala=fora_escala, almoco_a_partir=6 * 3600,
        )

    def test_parametros_por_jornada(self):
        self.assertEqual(Config.parametros_jornada(12), (12 * 3600, 0))
        self.assertEqual(
            Config.parametros_jornada(8),
            (Config.JORNADA_PADRAO_SEGUNDOS, Config.ALMOCO_SEGUNDOS),
        )

    def test_plantao_de_12_horas_nao_tem_excedente_nem_almoco(self):
        perm, almoco, trab, exced = self.plantao("7:00", "19:00")
        self.assertEqual(format_duration(perm), "12:00")
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "12:00")
        self.assertEqual(exced, 0)

    def test_plantao_passando_de_12_horas_gera_excedente(self):
        _, _, trab, exced = self.plantao("7:00", "20:30")
        self.assertEqual(format_duration(trab), "12:00")
        self.assertEqual(format_duration(exced), "1:30")

    def test_plantao_noturno_vira_a_meia_noite(self):
        perm, _, trab, exced = self.plantao("19:00", "7:00")
        self.assertEqual(format_duration(perm), "12:00")
        self.assertEqual(exced, 0)

    def test_plantao_curto_fica_devendo(self):
        _, _, trab, exced = self.plantao("7:00", "15:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(format_duration(exced), "-4:00")

    def test_plantao_no_dia_de_folga_e_todo_excedente(self):
        perm, _, trab, exced = self.plantao("7:00", "19:00", fora_escala=True)
        self.assertEqual(format_duration(perm), "12:00")
        self.assertEqual(trab, 0)
        self.assertEqual(format_duration(exced), "12:00")

    def test_jornada_cumprida_zera_o_excedente(self):
        # 8:00 as 17:00: 9h de permanencia, menos 1h de almoco, 8h trabalhadas.
        _, _, trab, exced = self.jornada("8:00", "17:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(exced, 0)

    def test_virada_de_meia_noite(self):
        perm, _, trab, exced = self.jornada("22:00", "7:00")
        self.assertEqual(format_duration(perm), "9:00")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(exced, 0)


# ------------------------------------------------------------- repo falso
class RepoFalso:
    """Guarda tudo em memoria e registra o que foi gravado."""

    def __init__(self):
        self.gravacoes = []
        self._fechamentos = []
        self._unidades = [{"id": 18, "nome": "Detran"}, {"id": 19, "nome": "SMA"}]
        self._funcionarios = [{
            "id": 1, "nome": "Alexandre P. S. Raia", "prontuario": "25755",
            "telefone": "(11)975492889", "cargo": "Analista de TI",
            "unidade": "Detran", "unidade_ids": [18], "ativo": True, "jornada_horas": 8,
        }, {
            "id": 27, "nome": "Anderson", "prontuario": "48906",
            "telefone": "(11)914127164", "cargo": "Motorista",
            "unidade": "Detran", "unidade_ids": [18], "ativo": True, "jornada_horas": 8,
        }, {
            "id": 30, "nome": "Paulo Plantao", "prontuario": "70001",
            "telefone": "", "cargo": "Plantonista",
            "unidade": "Detran", "unidade_ids": [18], "ativo": True, "jornada_horas": 12,
        }]
        self._usuarios = [
            self._usuario(1, "Alexandre Raia", "alexandre", "Administrador"),
            self._usuario(2, "Flavio Galisteu", "flavio", "RH"),
            self._usuario(3, "Fernando Cruz", "fernando", "Gestor"),
            self._usuario(4, "Veridiana", "veridiana", "Operacoes"),
        ]
        self._lancamentos = {
            100: self._lanc(100, "25755", "Alexandre P. S. Raia", "Pendente"),
            101: self._lanc(101, "48906", "Anderson", "Aprovado"),
            102: self._lanc(102, "48906", "Anderson", "Pendente", "2026-10-02"),
        }

    @staticmethod
    def _usuario(row_id, nome, login, perfil):
        return {
            "id": row_id, "nome": nome, "login": login, "perfil": perfil,
            "hash": hash_senha("senha123"), "ativo": True,
        }

    @staticmethod
    def _lanc(row_id, prontuario, nome, status, data="2026-10-01"):
        entrada, saida = 8 * 3600, 19 * 3600 + 1800
        perm, almoco, trab, exced = calcula_jornada(entrada, saida, 8 * 3600, 3600)
        _, _, _, exced_hc = calcula_jornada(
            entrada, saida, 8 * 3600, 3600, hc_autorizada=True
        )
        return {
            "id": row_id, "prontuario": prontuario, "funcionario": nome,
            "funcionario_ids": [1], "data": data,
            "data_br": "/".join(reversed(data.split("-"))),
            "entrada_seg": entrada, "saida_seg": saida,
            "permanencia_seg": perm, "almoco_seg": almoco,
            "trabalhadas_seg": trab,
            # A hora corrida pedida e ainda pendente ja vale no calculo.
            "excedidas_seg": exced_hc, "excedidas_calc_seg": exced_hc,
            "excedidas_sem_hc_seg": exced, "excedidas_com_hc_seg": exced_hc,
            "status": status, "hc_solicitada": True, "hc_status": "Pendente",
            "obs_rh": "", "parecer": "", "unidade": "Detran",
            "jornada_horas": 8, "fora_escala": False,
            "ajustado": False,
            "lancado_por": "Flavio Galisteu", "lancado_em": "01/10/2026 18:00",
            "decidido_por": "", "decidido_em": "",
        }

    # --- leitura
    def unidades(self):
        return list(self._unidades)

    def unidade(self, row_id):
        return next(u for u in self._unidades if u["id"] == row_id)

    def funcionarios(self, somente_ativos=False):
        return list(self._funcionarios)

    def funcionario(self, row_id):
        return next(f for f in self._funcionarios if f["id"] == row_id)

    def funcionario_por_prontuario(self, prontuario):
        return next((f for f in self._funcionarios if f["prontuario"] == prontuario), None)

    def funcionario_criar(self, dados):
        self.funcionario_gravado = dados
        return {"id": 999}

    def funcionario_atualizar(self, row_id, dados):
        self.funcionario_gravado = dados

    def usuarios(self):
        return list(self._usuarios)

    def usuario_por_login(self, login):
        alvo = (login or "").lower()
        return next((u for u in self._usuarios if u["login"] == alvo), None)

    def lancamentos(self, inicio=None, fim=None, prontuario=None, status=None,
                    unidade=None, hc_status=None):
        itens = list(self._lancamentos.values())
        if prontuario:
            itens = [i for i in itens if i["prontuario"] == prontuario]
        if status:
            itens = [i for i in itens if i["status"] == status]
        return itens

    def lancamento(self, row_id):
        return dict(self._lancamentos[row_id])

    def existe_lancamento(self, prontuario, data_iso, ignorar_id=None):
        return None

    # --- fechamento
    def fechamento(self, ano, mes):
        return next(
            (f for f in self._fechamentos
             if (f["ano"], f["mes"]) == (ano, mes) and not f["reaberto_em"]), None)

    def mes_fechado_data(self, data_iso):
        return bool(data_iso) and self.fechamento(int(data_iso[:4]), int(data_iso[5:7])) is not None

    def fechamentos_do_ano(self, ano):
        return [f for f in self._fechamentos if f["ano"] == ano]

    def pendencias_do_ano(self, ano):
        n = {}
        for i in self._lancamentos.values():
            if not i["data"].startswith(str(ano)):
                continue
            pendente = (i["status"] == "Pendente"
                        and ((i["excedidas_seg"] or 0) != 0 or i["hc_solicitada"])) \
                or (i["hc_solicitada"] and i["hc_status"] == "Pendente")
            if pendente:
                mes = int(i["data"][5:7])
                n[mes] = n.get(mes, 0) + 1
        return n

    def fechar_mes(self, ano, mes, por):
        if self.fechamento(ano, mes) or self.pendencias_do_ano(ano).get(mes):
            return False
        self._fechamentos.append({
            "id": len(self._fechamentos) + 1, "ano": ano, "mes": mes,
            "fechado_por": por, "fechado_em": "11/10/2026 10:00",
            "reaberto_por": "", "reaberto_em": "", "motivo": "",
        })
        self.gravacoes.append(("fechar", ano, mes))
        return True

    def reabrir_mes(self, ano, mes, por, motivo):
        atual = self.fechamento(ano, mes)
        if not atual:
            return False
        atual.update(reaberto_por=por, reaberto_em="11/10/2026 11:00", motivo=motivo)
        self.gravacoes.append(("reabrir", ano, mes, motivo))
        return True

    def _garante_aberto(self, data_iso):
        if self.mes_fechado_data(data_iso):
            raise MesFechado(int(data_iso[:4]), int(data_iso[5:7]))

    # --- escrita
    def lancamento_criar(self, payload):
        self._garante_aberto(payload.get(S.F["lanc_data"]))
        self.gravacoes.append(("criar", payload))
        return {"id": 999}

    def lancamento_atualizar(self, row_id, payload):
        self._garante_aberto(self._lancamentos[row_id]["data"])
        self.gravacoes.append(("atualizar", row_id, payload))
        self._lancamentos[row_id].update(
            {"status": payload.get(S.F["lanc_status"], self._lancamentos[row_id]["status"])}
        )
        return {"id": row_id}

    def lancamento_excluir(self, row_id):
        self._garante_aberto(self._lancamentos[row_id]["data"])
        self.gravacoes.append(("excluir", row_id))


# ------------------------------------------------------------------ rotas
class BaseWeb(unittest.TestCase):
    def setUp(self):
        self.repo = RepoFalso()
        set_repo(self.repo)
        Config.SECRET_KEY = "teste"
        self.app = create_app(Config)
        self.app.config.update(TESTING=True, SECRET_KEY="teste")
        self.cliente = self.app.test_client()

    def entrar(self, login):
        return self.cliente.post(
            "/login", data={"login": login, "senha": "senha123"}, follow_redirects=True
        )


class TestLogin(BaseWeb):
    def test_senha_errada_nao_entra(self):
        resposta = self.cliente.post(
            "/login", data={"login": "flavio", "senha": "errada"}, follow_redirects=True
        )
        self.assertIn("inv", resposta.get_data(as_text=True).lower())

    def test_login_do_rh_cai_nos_lancamentos(self):
        resposta = self.entrar("flavio")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Lançamentos", resposta.get_data(as_text=True))

    def test_login_do_gestor_cai_nas_aprovacoes(self):
        resposta = self.entrar("fernando")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Aprovações", resposta.get_data(as_text=True))

    def test_sem_login_vai_para_a_tela_de_entrada(self):
        resposta = self.cliente.get("/lancamentos/", follow_redirects=False)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/login", resposta.headers["Location"])


class TestPermissoes(BaseWeb):
    def test_rh_lanca_mas_nao_aprova(self):
        self.entrar("flavio")
        self.assertEqual(self.cliente.get("/lancamentos/novo").status_code, 200)
        self.assertEqual(self.cliente.get("/aprovacoes/").status_code, 403)

    def test_gestor_aprova_mas_nao_lanca(self):
        self.entrar("fernando")
        self.assertEqual(self.cliente.get("/aprovacoes/").status_code, 200)
        self.assertEqual(self.cliente.get("/lancamentos/novo").status_code, 403)

    def test_operacoes_so_consulta(self):
        self.entrar("veridiana")
        self.assertEqual(self.cliente.get("/lancamentos/").status_code, 200)
        self.assertEqual(self.cliente.get("/relatorios").status_code, 200)
        self.assertEqual(self.cliente.get("/lancamentos/novo").status_code, 403)
        self.assertEqual(self.cliente.get("/aprovacoes/").status_code, 403)
        self.assertEqual(self.cliente.get("/cadastros/usuarios").status_code, 403)

    def test_apenas_admin_mantem_cadastros(self):
        self.entrar("alexandre")
        for rota in ("/cadastros/usuarios", "/cadastros/funcionarios", "/cadastros/unidades"):
            self.assertEqual(self.cliente.get(rota).status_code, 200, rota)
        self.assertEqual(self.cliente.get("/aprovacoes/").status_code, 403)
        self.assertEqual(self.cliente.get("/lancamentos/novo").status_code, 403)


class TestHoraCorridaNoRepositorio(unittest.TestCase):
    """Repo._map_lancamento de verdade, sem banco: a hora corrida ja conta."""

    def mapeia(self, hc_solicitada, hc_status, manual=None):
        repo = Repo.__new__(Repo)
        repo.config = Config
        linha = {
            "id": 1, "prontuario": "25755", "funcionario": "Alexandre",
            "funcionario_id": 1, "jornada_horas": 8, "fora_escala": False,
            "data": date(2026, 10, 5), "entrada_seg": 8 * 3600, "saida_seg": 19 * 3600,
            "status": "Pendente", "hc_solicitada": hc_solicitada, "hc_status": hc_status,
            "obs_rh": "", "parecer_gestor": "", "unidade": "Detran",
            "lancado_por": "", "lancado_em": None, "decidido_por": "", "decidido_em": None,
            "excedidas_manual_seg": manual,
        }
        return repo._map_lancamento(linha)

    def horas(self, item):
        return format_duration(item["excedidas_seg"])

    def test_sem_hora_corrida_o_almoco_e_descontado(self):
        self.assertEqual(self.horas(self.mapeia(False, "Nao solicitada")), "2:00")

    def test_hora_corrida_pendente_ja_conta(self):
        item = self.mapeia(True, "Pendente")
        self.assertEqual(self.horas(item), "3:00")
        self.assertEqual(format_duration(item["excedidas_sem_hc_seg"]), "2:00")

    def test_hora_corrida_autorizada_continua_contando(self):
        self.assertEqual(self.horas(self.mapeia(True, "Autorizada")), "3:00")

    def test_hora_corrida_negada_refaz_o_calculo(self):
        item = self.mapeia(True, "Negada")
        self.assertEqual(self.horas(item), "2:00")
        self.assertEqual(format_duration(item["excedidas_com_hc_seg"]), "3:00")

    def test_ajuste_manual_vale_em_qualquer_situacao(self):
        for situacao in ("Pendente", "Autorizada", "Negada"):
            item = self.mapeia(True, situacao, manual=-1800)
            self.assertEqual(self.horas(item), "-0:30", situacao)
            self.assertTrue(item["ajustado"])


HX = {"HX-Request": "true"}


class TestModalDeEdicao(BaseWeb):
    DADOS = {"data": "2026-10-01", "funcionario_id": "1", "entrada": "8:00",
             "saida": "17:00", "voltar": "/lancamentos/?mes=10&ano=2026&prontuario=25755"}

    def test_lista_tem_o_modal_e_o_botao_abre_nele(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/?mes=10&ano=2026").get_data(as_text=True)
        self.assertIn('<dialog id="modal"', html)
        self.assertIn('id="lista"', html)
        self.assertIn('hx-get="/lancamentos/100/editar?', html)
        self.assertIn('hx-target="#modal-corpo"', html)
        # Sem JavaScript o mesmo botao continua sendo um link para a pagina.
        self.assertIn('href="/lancamentos/100/editar?', html)

    def test_gestor_nao_ve_o_modal(self):
        self.entrar("fernando")
        html = self.cliente.get("/lancamentos/?mes=10&ano=2026").get_data(as_text=True)
        self.assertNotIn('<dialog id="modal"', html)

    def test_htmx_recebe_so_o_formulario(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/100/editar", headers=HX).get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertIn('hx-post="/lancamentos/100/editar"', html)
        self.assertIn('name="voltar"', html)
        self.assertIn("onclick=\"document.getElementById('modal').close()\"", html)

    def test_sem_htmx_continua_a_pagina_inteira(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/100/editar").get_data(as_text=True)
        self.assertIn("<html", html)
        self.assertNotIn("hx-post", html)
        self.assertIn('action="/lancamentos/100/editar"', html)

    def test_salvar_no_modal_devolve_a_lista_e_manda_fechar(self):
        self.entrar("flavio")
        resposta = self.cliente.post("/lancamentos/100/editar", data=self.DADOS, headers=HX)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.headers["HX-Retarget"], "#lista")
        self.assertEqual(resposta.headers["HX-Reswap"], "outerHTML")
        self.assertEqual(resposta.headers["HX-Trigger"], "modal-fechar")
        html = resposta.get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertIn('id="lista"', html)
        self.assertIn("Lancamento atualizado", html)
        self.assertEqual(self.repo.gravacoes[-1][0], "atualizar")

    def test_lista_devolvida_respeita_os_filtros_da_pagina(self):
        self.entrar("flavio")
        html = self.cliente.post(
            "/lancamentos/100/editar", data=self.DADOS, headers=HX).get_data(as_text=True)
        # Filtro por prontuario 25755: so o funcionario dele fica na lista.
        self.assertIn("Alexandre P. S. Raia", html)
        self.assertNotIn("<strong>Anderson</strong>", html)

    def test_erro_no_modal_mantem_o_formulario_aberto(self):
        self.entrar("flavio")
        dados = {**self.DADOS, "entrada": "", "saida": ""}
        resposta = self.cliente.post("/lancamentos/100/editar", data=dados, headers=HX)
        self.assertNotIn("HX-Retarget", resposta.headers)
        html = resposta.get_data(as_text=True)
        self.assertIn("Informe a entrada", html)
        self.assertIn('hx-post="/lancamentos/100/editar"', html)
        self.assertEqual(self.repo.gravacoes, [])

    def test_sem_htmx_salvar_redireciona_para_a_lista_filtrada(self):
        self.entrar("flavio")
        resposta = self.cliente.post("/lancamentos/100/editar", data=self.DADOS)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("prontuario=25755", resposta.headers["Location"])

    def test_voltar_de_fora_do_sistema_e_ignorado(self):
        self.entrar("flavio")
        for ruim in ("https://evil.example/", "//evil.example/", "/aprovacoes/"):
            resposta = self.cliente.post(
                "/lancamentos/100/editar", data={**self.DADOS, "voltar": ruim})
            self.assertEqual(resposta.status_code, 302)
            self.assertTrue(resposta.headers["Location"].endswith("/lancamentos/"), ruim)

    def test_modal_de_mes_fechado_avisa_sem_trazer_a_pagina_inteira(self):
        self.repo._fechamentos.append({
            "id": 1, "ano": 2026, "mes": 10, "fechado_por": "Fernando Cruz",
            "fechado_em": "11/10/2026 10:00", "reaberto_por": "", "reaberto_em": "",
            "motivo": "",
        })
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/100/editar", headers=HX).get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertIn("ja foi fechado", html)

    def test_lancar_o_dia_tambem_abre_no_modal(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/novo", headers=HX).get_data(as_text=True)
        self.assertNotIn("<html", html)
        self.assertIn('hx-post="/lancamentos/novo"', html)
        resposta = self.cliente.post(
            "/lancamentos/novo", headers=HX,
            data={**self.DADOS, "data": "2026-10-09", "funcionario_id": "27"})
        self.assertEqual(resposta.headers["HX-Trigger"], "modal-fechar")
        self.assertEqual(self.repo.gravacoes[-1][0], "criar")


class TestAjusteDoExcedente(BaseWeb):
    # 8:00 as 19:00 de um funcionario de 8h: calculado 2:00 (sem hora corrida).
    BASE = {"data": "2026-10-05", "funcionario_id": "1", "entrada": "8:00", "saida": "19:00"}

    def envia(self, rota="/lancamentos/novo", **extra):
        self.entrar("flavio")
        return self.cliente.post(rota, data={**self.BASE, **extra}, follow_redirects=True)

    def gravado(self):
        return self.repo.gravacoes[-1][-1]

    def test_em_branco_usa_o_calculo(self):
        self.envia()
        payload = self.gravado()
        self.assertEqual(payload[S.F["lanc_excedidas"]], 2 * 3600)
        self.assertIsNone(payload[S.F["lanc_excedidas_manual"]])

    def test_valor_digitado_vale_no_lugar_do_calculo(self):
        self.envia(excedente="1:30", obs_rh="saiu mais cedo para consulta")
        payload = self.gravado()
        self.assertEqual(payload[S.F["lanc_excedidas_manual"]], 90 * 60)
        self.assertEqual(payload[S.F["lanc_excedidas"]], 90 * 60)

    def test_aceita_horas_negativas(self):
        self.envia(excedente="-0:30", obs_rh="compensar na proxima semana")
        payload = self.gravado()
        self.assertEqual(payload[S.F["lanc_excedidas_manual"]], -30 * 60)
        self.assertEqual(payload[S.F["lanc_excedidas"]], -30 * 60)

    def test_ajuste_exige_o_motivo(self):
        resposta = self.envia(excedente="1:00")
        self.assertIn("motivo do ajuste", resposta.get_data(as_text=True))
        self.assertEqual(self.repo.gravacoes, [])

    def test_valor_igual_ao_calculado_nao_e_ajuste_e_nao_exige_motivo(self):
        self.envia(excedente="2:00")
        self.assertIsNone(self.gravado()[S.F["lanc_excedidas_manual"]])

    def test_formato_invalido_e_limite(self):
        for ruim in ("abc", "25:00", "-21:00"):
            self.repo.gravacoes.clear()
            self.envia(excedente=ruim, obs_rh="x")
            self.assertEqual(self.repo.gravacoes, [], ruim)

    def test_editar_pode_voltar_ao_calculo(self):
        self.envia("/lancamentos/100/editar", excedente="", obs_rh="")
        self.assertIsNone(self.gravado()[S.F["lanc_excedidas_manual"]])

    def test_ajuste_em_mes_fechado_e_barrado(self):
        self.repo._fechamentos.append({
            "id": 1, "ano": 2026, "mes": 10, "fechado_por": "Fernando Cruz",
            "fechado_em": "11/10/2026 10:00", "reaberto_por": "", "reaberto_em": "",
            "motivo": "",
        })
        self.envia("/lancamentos/100/editar", excedente="1:00", obs_rh="x")
        self.assertEqual(self.repo.gravacoes, [])

    def test_gestor_nao_apaga_o_ajuste_ao_decidir_a_hora_corrida(self):
        self.repo._lancamentos[100].update(
            ajustado=True, excedidas_seg=90 * 60, excedidas_calc_seg=2 * 3600)
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Autorizada"})
        self.assertNotIn(S.F["lanc_excedidas"], self.gravado())

    def test_lista_e_analise_mostram_o_ajuste(self):
        self.repo._lancamentos[100].update(
            ajustado=True, excedidas_seg=-30 * 60, excedidas_calc_seg=2 * 3600,
            obs_rh="compensar")
        self.entrar("fernando")
        self.assertIn("Ajustado", self.cliente.get("/aprovacoes/?status=").get_data(as_text=True))
        html = self.cliente.get("/aprovacoes/100").get_data(as_text=True)
        self.assertIn("O RH ajustou o excedente", html)
        self.assertIn("compensar", html)

    def test_valor_negativo_ainda_exige_decisao(self):
        lanc = self.repo._lancamentos[100]
        lanc.update(hc_solicitada=False, hc_status="Nao solicitada", excedidas_seg=-30 * 60)
        self.repo._lancamentos = {100: lanc}
        self.assertEqual(self.repo.pendencias_do_ano(2026), {10: 1})
        lanc["excedidas_seg"] = 0
        self.assertEqual(self.repo.pendencias_do_ano(2026), {})

    def test_csv_traz_calculado_e_ajustado(self):
        self.repo._lancamentos[100].update(
            ajustado=True, excedidas_seg=60 * 60, excedidas_calc_seg=2 * 3600)
        self.entrar("veridiana")
        csv = self.cliente.get("/relatorios/csv").get_data(as_text=True)
        self.assertIn("Excedente calculado;Ajustado pelo RH", csv)
        self.assertIn("2:00;Sim", csv)


class TestPlantonista(BaseWeb):
    def lanca(self, funcionario_id, **extra):
        self.entrar("flavio")
        dados = {"data": "2026-10-05", "funcionario_id": funcionario_id,
                 "entrada": "7:00", "saida": "19:00", **extra}
        self.cliente.post("/lancamentos/novo", data=dados)
        acao, payload = self.repo.gravacoes[-1]
        self.assertEqual(acao, "criar")
        return payload

    def test_plantao_normal_nao_gera_excedente(self):
        payload = self.lanca("30")
        self.assertEqual(payload[S.F["lanc_excedidas"]], 0)
        self.assertFalse(payload[S.F["lanc_fora_escala"]])

    def test_plantao_no_dia_de_folga_conta_inteiro_como_excedente(self):
        payload = self.lanca("30", fora_escala="on")
        self.assertTrue(payload[S.F["lanc_fora_escala"]])
        self.assertEqual(payload[S.F["lanc_excedidas"]], 12 * 3600)

    def test_plantonista_nao_pede_hora_corrida(self):
        payload = self.lanca("30", hc_solicitada="on")
        self.assertFalse(payload[S.F["lanc_hc_solicitada"]])
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Nao solicitada")

    def test_folga_so_vale_para_plantonista(self):
        payload = self.lanca("1", fora_escala="on")
        self.assertFalse(payload[S.F["lanc_fora_escala"]])

    def test_cadastro_grava_a_jornada(self):
        self.entrar("alexandre")
        self.cliente.post("/cadastros/funcionarios/salvar", data={
            "nome": "Novo", "prontuario": "999", "jornada_horas": "12", "ativo": "on"})
        self.assertEqual(self.repo.funcionario_gravado["jornada_horas"], 12)


class TestFiltroPorFuncionario(BaseWeb):
    def test_todas_as_listas_oferecem_o_filtro(self):
        for login, rota in (
            ("flavio", "/lancamentos/"),
            ("fernando", "/aprovacoes/"),
            ("veridiana", "/relatorios"),
        ):
            self.cliente.get("/logout")
            self.entrar(login)
            html = self.cliente.get(rota).get_data(as_text=True)
            self.assertIn('name="prontuario"', html, rota)

    def test_aprovacoes_e_relatorio_filtram_pelo_funcionario(self):
        self.entrar("fernando")
        html = self.cliente.get("/aprovacoes/?status=&prontuario=25755").get_data(as_text=True)
        self.assertIn("Alexandre P. S. Raia", html.split("<tbody", 1)[1])
        self.assertNotIn("<strong>Anderson</strong>", html)
        self.cliente.get("/logout")
        self.entrar("veridiana")
        html = self.cliente.get("/relatorios?prontuario=48906").get_data(as_text=True)
        self.assertNotIn("<strong>Alexandre P. S. Raia</strong>", html)
        csv = self.cliente.get("/relatorios/csv?prontuario=48906").get_data(as_text=True)
        self.assertIn("48906", csv)
        self.assertNotIn("25755", csv)


class TestSeparacaoDeFuncoes(BaseWeb):
    def test_rh_edita_lancamento_decidido_e_ele_volta_ao_gestor(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/101/editar").get_data(as_text=True)
        self.assertIn("decisão é desfeita", html)
        resposta = self.cliente.post(
            "/lancamentos/101/editar",
            data={"data": "2026-10-01", "funcionario_id": "27",
                  "entrada": "8:00", "saida": "17:00"},
            follow_redirects=True,
        )
        self.assertIn("voltou para nova decisao", resposta.get_data(as_text=True))
        acao, row_id, payload = self.repo.gravacoes[-1]
        self.assertEqual((acao, row_id), ("atualizar", 101))
        # O RH so devolve o lancamento: a unica situacao que grava e Pendente.
        self.assertEqual(payload[S.F["lanc_status"]], "Pendente")
        self.assertEqual(payload[S.F["lanc_decidido_por"]], "")
        self.assertIsNone(payload[S.F["lanc_decidido_em"]])
        self.assertEqual(payload[S.F["lanc_parecer"]], "")

    def test_rh_exclui_lancamento_ja_decidido_com_o_mes_aberto(self):
        self.entrar("flavio")
        self.cliente.post("/lancamentos/101/excluir", follow_redirects=True)
        self.assertEqual(self.repo.gravacoes, [("excluir", 101)])

    def test_gestor_e_operacoes_nao_excluem(self):
        for login in ("fernando", "veridiana", "alexandre"):
            self.cliente.get("/logout")
            self.entrar(login)
            resposta = self.cliente.post("/lancamentos/100/excluir")
            self.assertEqual(resposta.status_code, 403, login)
        self.assertEqual(self.repo.gravacoes, [])

    def test_botoes_editar_e_excluir_com_icone_em_qualquer_situacao(self):
        self.entrar("flavio")
        html = self.cliente.get("/lancamentos/").get_data(as_text=True)
        for row_id in (100, 101):
            self.assertIn(f"/lancamentos/{row_id}/editar", html)
            self.assertIn(f"/lancamentos/{row_id}/excluir", html)
        self.assertIn("M10.8 2.7", html, "icone de lapis")
        self.assertIn("M6.2 4.5V3", html, "icone de lixeira")

    def test_rh_edita_enquanto_pendente(self):
        self.entrar("flavio")
        resposta = self.cliente.post(
            "/lancamentos/100/editar",
            data={"data": "2026-10-01", "funcionario_id": "1",
                  "entrada": "8:00", "saida": "18:00"},
            follow_redirects=True,
        )
        self.assertEqual(resposta.status_code, 200)
        acao, row_id, payload = self.repo.gravacoes[-1]
        self.assertEqual((acao, row_id), ("atualizar", 100))
        # O RH nao decide: so pode gravar Pendente, nunca Aprovado/Rejeitado.
        self.assertEqual(payload[S.F["lanc_status"]], "Pendente")
        self.assertEqual(payload[S.F["lanc_parecer"]], "")
        # 8:00 as 18:00 = 10h de permanencia, menos 1h de almoco, menos 8h
        self.assertEqual(payload[S.F["lanc_excedidas"]], 3600)

    def test_gestor_decide_sem_tocar_nas_horas(self):
        self.entrar("fernando")
        resposta = self.cliente.post(
            "/aprovacoes/100",
            data={"decisao": "Aprovado", "hc_decisao": "Autorizada", "parecer": "ok"},
            follow_redirects=True,
        )
        self.assertEqual(resposta.status_code, 200)
        acao, row_id, payload = self.repo.gravacoes[-1]
        self.assertEqual((acao, row_id), ("atualizar", 100))
        self.assertEqual(payload[S.F["lanc_status"]], "Aprovado")
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Autorizada")
        self.assertEqual(payload[S.F["lanc_decidido_por"]], "Fernando Cruz")
        # O gestor nao encosta no que o RH apurou. O excedente e a unica hora
        # que ele move, e so como consequencia da hora corrida que ele decidiu.
        for proibido in ("lanc_entrada", "lanc_saida", "lanc_data",
                         "lanc_prontuario", "lanc_obs_rh", "lanc_funcionario"):
            self.assertNotIn(S.F[proibido], payload)

    def test_autorizar_hc_nao_muda_o_excedente_que_ja_contava_a_hora_corrida(self):
        self.entrar("fernando")
        antes = self.repo.lancamento(100)
        self.cliente.post("/aprovacoes/100", data={
            "decisao": "Aprovado", "hc_decisao": "Autorizada", "parecer": "nao almocou",
        }, follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Autorizada")
        # A hora do almoco ja estava no excedente desde o lancamento: 3:30.
        self.assertEqual(antes["excedidas_seg"], 3 * 3600 + 1800)
        self.assertNotIn(S.F["lanc_excedidas"], payload)

    def test_negar_hc_refaz_o_calculo_com_o_almoco_descontado(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100", data={
            "decisao": "Aprovado", "hc_decisao": "Negada", "parecer": "almocou",
        }, follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Negada")
        self.assertEqual(payload[S.F["lanc_excedidas"]], 2 * 3600 + 1800)

    def test_rejeicao_exige_parecer(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100", data={"decisao": "Rejeitado", "parecer": ""})
        self.assertEqual(self.repo.gravacoes, [])


class TestTelas(BaseWeb):
    def test_telas_de_consulta_renderizam(self):
        self.entrar("flavio")
        for rota in ("/", "/lancamentos/", "/lancamentos/novo", "/relatorios"):
            resposta = self.cliente.get(rota, follow_redirects=True)
            self.assertEqual(resposta.status_code, 200, rota)

    def test_raiz_encaminha_por_perfil(self):
        self.entrar("fernando")
        resposta = self.cliente.get("/")
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/aprovacoes/", resposta.headers["Location"])
        self.cliente.get("/logout")
        self.entrar("veridiana")
        resposta = self.cliente.get("/")
        self.assertIn("/lancamentos/", resposta.headers["Location"])

    def test_exportacao_csv(self):
        self.entrar("veridiana")
        resposta = self.cliente.get("/relatorios/csv?ano=2026&mes=10")
        self.assertEqual(resposta.status_code, 200)
        texto = resposta.get_data(as_text=True)
        self.assertIn("Horas excedidas", texto)
        self.assertIn("25755", texto)


class TestBotoesDeDecisao(BaseWeb):
    """Um clique no botao grava uma decisao so, sem mexer no resto."""

    def test_botao_aprovar_horas(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/horas", data={"valor": "Aprovado"},
                          follow_redirects=True)
        _, row_id, payload = self.repo.gravacoes[-1]
        self.assertEqual(row_id, 100)
        self.assertEqual(payload[S.F["lanc_status"]], "Aprovado")
        self.assertNotIn(S.F["lanc_hc_status"], payload)

    def test_botao_reprovar_horas(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/horas", data={"valor": "Rejeitado"},
                          follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_status"]], "Rejeitado")

    def test_autorizar_hc_na_linha_confirma_sem_mudar_o_excedente(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Autorizada"},
                          follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Autorizada")
        # A hora corrida ja contava desde o lancamento: nada a recalcular.
        self.assertNotIn(S.F["lanc_excedidas"], payload)
        # Decidir a hora corrida nao decide as horas excedentes.
        self.assertNotIn(S.F["lanc_status"], payload)

    def test_negar_hc_na_linha_refaz_o_calculo(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Negada"},
                          follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Negada")
        # O almoco volta a ser descontado: 3:30 vira 2:30.
        self.assertEqual(payload[S.F["lanc_excedidas"]], 2 * 3600 + 1800)

    def test_hc_nao_pedida_nao_se_decide(self):
        self.repo._lancamentos[100]["hc_solicitada"] = False
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Autorizada"},
                          follow_redirects=True)
        self.assertEqual(self.repo.gravacoes, [])

    def test_botoes_so_para_o_que_falta_decidir(self):
        # 100 pendente com HC a decidir; 101 aprovado; 102 pendente sem HC.
        self.repo._lancamentos[101]["hc_status"] = "Autorizada"
        self.repo._lancamentos[102]["hc_solicitada"] = False
        self.entrar("fernando")
        html = self.cliente.get("/lancamentos/?mes=10&ano=2026").get_data(as_text=True)
        self.assertEqual(html.count('name="valor" value="Aprovado"'), 2)  # 100 e 102
        # 101 ja aprovado: so a opcao contraria, escondida no "alterar".
        self.assertEqual(html.count('name="valor" value="Rejeitado"'), 3)
        self.assertEqual(html.count("<summary>alterar</summary>"), 2)
        self.assertEqual(html.count('name="valor" value="Autorizada"'), 1)  # so 100
        self.assertIn("Não pedida", html)

    def test_valor_invalido_nao_grava(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/horas", data={"valor": "Talvez"},
                          follow_redirects=True)
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Talvez"},
                          follow_redirects=True)
        self.assertEqual(self.repo.gravacoes, [])

    def test_so_o_gestor_usa_os_botoes(self):
        for login in ("flavio", "veridiana", "alexandre"):
            self.cliente.get("/logout")
            self.entrar(login)
            for rota in ("/aprovacoes/100/horas", "/aprovacoes/100/hc"):
                resposta = self.cliente.post(rota, data={"valor": "Aprovado"})
                self.assertEqual(resposta.status_code, 403, f"{login} {rota}")
        self.assertEqual(self.repo.gravacoes, [])

    def test_volta_para_a_pagina_de_origem(self):
        self.entrar("fernando")
        resposta = self.cliente.post(
            "/aprovacoes/100/horas",
            data={"valor": "Aprovado", "voltar": "/lancamentos/?ano=2026&mes=10"},
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/lancamentos/", resposta.headers["Location"])

    def test_nao_aceita_destino_externo(self):
        self.entrar("fernando")
        resposta = self.cliente.post(
            "/aprovacoes/100/horas",
            data={"valor": "Aprovado", "voltar": "//site-de-fora.com"},
        )
        self.assertIn("/aprovacoes/", resposta.headers["Location"])


class TestAgrupamento(unittest.TestCase):
    def setUp(self):
        self.itens = list(RepoFalso()._lancamentos.values())

    def test_um_grupo_por_funcionario_em_ordem(self):
        grupos = agrupa_por_funcionario(self.itens)
        self.assertEqual([g["funcionario"] for g in grupos],
                         ["Alexandre P. S. Raia", "Anderson"])

    def test_subtotal_soma_os_dias_do_grupo(self):
        anderson = agrupa_por_funcionario(self.itens)[1]
        self.assertEqual(anderson["dias"], 2)
        um_dia = self.itens[1]["excedidas_seg"]
        self.assertEqual(anderson["excedidas"], 2 * um_dia)
        self.assertEqual(anderson["aprovadas"], um_dia)
        self.assertEqual(anderson["pendentes"], um_dia)

    def test_dias_do_grupo_em_ordem_de_data(self):
        anderson = agrupa_por_funcionario(self.itens)[1]
        self.assertEqual([i["data"] for i in anderson["itens"]],
                         ["2026-10-01", "2026-10-02"])


class TestLancamentoNovo(BaseWeb):
    def test_novo_lancamento_calcula_excedente(self):
        self.entrar("flavio")
        self.cliente.post(
            "/lancamentos/novo",
            data={"data": "2026-10-02", "funcionario_id": "27",
                  "entrada": "8:00", "saida": "20:00", "hc_solicitada": "on"},
            follow_redirects=True,
        )
        acao, payload = self.repo.gravacoes[-1]
        self.assertEqual(acao, "criar")
        # 8:00 as 20:00 = 12h de permanencia. Com hora corrida pedida o almoco
        # nao e descontado e o excedente ja nasce com ele: 12h - 8h = 4h.
        self.assertEqual(payload[S.F["lanc_excedidas"]], 4 * 3600)
        self.assertEqual(payload[S.F["lanc_status"]], "Pendente")
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Pendente")
        self.assertEqual(payload[S.F["lanc_lancado_por"]], "Flavio Galisteu")


class TestFechamento(BaseWeb):
    """O gestor fecha o mes, o administrador reabre, e nada grava em mes fechado."""

    def decide_tudo(self):
        for i in self.repo._lancamentos.values():
            i["status"], i["hc_status"] = "Aprovado", "Autorizada"

    def como(self, login):
        self.cliente.get("/logout")
        self.entrar(login)

    def fecha_outubro(self):
        self.decide_tudo()
        self.como("fernando")
        self.cliente.post("/fechamento/2026/10/fechar")
        self.repo.gravacoes.clear()

    def test_nao_fecha_com_pendencia(self):
        self.como("fernando")
        resposta = self.cliente.post("/fechamento/2026/10/fechar", follow_redirects=True)
        self.assertIn("esperando decisao", resposta.get_data(as_text=True))
        self.assertIsNone(self.repo.fechamento(2026, 10))

    def test_gestor_fecha_quando_nao_ha_pendencia(self):
        self.decide_tudo()
        self.como("fernando")
        self.cliente.post("/fechamento/2026/10/fechar")
        fechamento = self.repo.fechamento(2026, 10)
        self.assertEqual(fechamento["fechado_por"], "Fernando Cruz")

    def test_so_o_gestor_fecha(self):
        self.decide_tudo()
        for login in ("flavio", "veridiana", "alexandre"):
            self.como(login)
            resposta = self.cliente.post("/fechamento/2026/10/fechar")
            self.assertEqual(resposta.status_code, 403, login)
        self.assertIsNone(self.repo.fechamento(2026, 10))

    def test_nao_fecha_mes_que_nao_comecou(self):
        self.como("fernando")
        self.cliente.post("/fechamento/2099/1/fechar")
        self.assertIsNone(self.repo.fechamento(2099, 1))

    def test_so_o_admin_reabre_e_com_motivo(self):
        self.fecha_outubro()
        for login in ("fernando", "flavio", "veridiana"):
            self.como(login)
            resposta = self.cliente.post("/fechamento/2026/10/reabrir", data={"motivo": "erro de digitacao"})
            self.assertEqual(resposta.status_code, 403, login)
        self.como("alexandre")
        self.cliente.post("/fechamento/2026/10/reabrir", data={"motivo": "  "})
        self.assertIsNotNone(self.repo.fechamento(2026, 10), "sem motivo nao reabre")
        self.cliente.post("/fechamento/2026/10/reabrir", data={"motivo": "erro de digitacao"})
        self.assertIsNone(self.repo.fechamento(2026, 10))
        self.assertEqual(self.repo.gravacoes[-1], ("reabrir", 2026, 10, "erro de digitacao"))

    def test_reaberto_volta_a_aceitar_gravacoes(self):
        self.fecha_outubro()
        self.como("alexandre")
        self.cliente.post("/fechamento/2026/10/reabrir", data={"motivo": "ajuste combinado"})
        self.como("fernando")
        self.cliente.post("/aprovacoes/100/horas", data={"valor": "Rejeitado"})
        self.assertEqual(self.repo.gravacoes[-1][0], "atualizar")

    def test_rh_nao_lanca_edita_nem_exclui_em_mes_fechado(self):
        self.fecha_outubro()
        self.como("flavio")
        resposta = self.cliente.post(
            "/lancamentos/novo",
            data={"data": "2026-10-15", "funcionario_id": "27", "entrada": "8:00", "saida": "20:00"},
        )
        self.assertIn("ja foi fechado", resposta.get_data(as_text=True))
        self.cliente.get("/lancamentos/100/editar")
        self.cliente.post("/lancamentos/100/editar", data={
            "data": "2026-10-01", "funcionario_id": "1", "entrada": "8:00", "saida": "21:00"})
        self.cliente.post("/lancamentos/100/excluir")
        self.assertEqual(self.repo.gravacoes, [])

    def test_gestor_nao_decide_em_mes_fechado(self):
        self.fecha_outubro()
        self.como("fernando")
        self.cliente.post("/aprovacoes/100/horas", data={"valor": "Rejeitado"})
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Negada"})
        self.cliente.post("/aprovacoes/100", data={"decisao": "Rejeitado", "parecer": "x", "hc_decisao": "Negada"})
        self.assertEqual(self.repo.gravacoes, [])
        self.assertEqual(self.repo._lancamentos[100]["status"], "Aprovado")

    def test_nao_existe_mais_decisao_em_lote(self):
        self.como("fernando")
        resposta = self.cliente.post(
            "/aprovacoes/lote", data={"decisao": "Aprovado", "selecionados": ["100", "102"]})
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.repo.gravacoes, [])
        html = self.cliente.get("/aprovacoes/").get_data(as_text=True)
        self.assertNotIn("Decisão em lote", html)
        self.assertNotIn('name="selecionados"', html)

    def test_listas_mostram_o_aviso_e_escondem_os_botoes(self):
        self.fecha_outubro()
        self.como("fernando")
        for rota in ("/aprovacoes/?mes=10&ano=2026&status=", "/lancamentos/?mes=10&ano=2026"):
            html = self.cliente.get(rota).get_data(as_text=True)
            self.assertIn("Mês fechado", html, rota)
            self.assertNotIn('name="valor" value="Aprovado"', html, rota)
            self.assertNotIn('name="valor" value="Autorizada"', html, rota)
        self.assertNotIn("Analisar", self.cliente.get("/aprovacoes/?mes=10&ano=2026&status=").get_data(as_text=True))
        self.como("flavio")
        html = self.cliente.get("/lancamentos/?mes=10&ano=2026").get_data(as_text=True)
        self.assertNotIn("/editar", html)
        self.assertIn("Mês fechado", html)
        self.assertIn("Mês fechado", self.cliente.get("/relatorios?mes=10&ano=2026").get_data(as_text=True))

    def test_pagina_de_fechamento_para_todos_os_perfis(self):
        for login in ("flavio", "fernando", "veridiana", "alexandre"):
            self.como(login)
            resposta = self.cliente.get("/fechamento/?ano=2026")
            self.assertEqual(resposta.status_code, 200, login)
        html = self.cliente.get("/fechamento/?ano=2026").get_data(as_text=True)
        self.assertNotIn(">Fechar mês<", html, "o admin nao fecha")
        self.como("fernando")
        self.assertIn("Fechar mês", self.cliente.get("/fechamento/?ano=2026").get_data(as_text=True))


class TestAtualizacaoParcial(BaseWeb):
    """htmx: so o bloco do funcionario e os totais mudam na tela."""

    def test_ident_gera_id_seguro(self):
        self.assertEqual(ident("22345"), "22345")
        self.assertEqual(ident("Ana Maria/2"), "Ana_Maria_2")

    def test_blocos_e_botoes_tem_os_atributos_do_htmx(self):
        self.entrar("fernando")
        html = self.cliente.get("/aprovacoes/?mes=10&ano=2026").get_data(as_text=True)
        self.assertIn('id="g-25755"', html)
        self.assertIn('hx-select="#g-25755"', html)
        self.assertIn('hx-select-oob="#avisos,#total-geral"', html)
        self.assertIn('hx-post="/aprovacoes/100/horas"', html)
        self.assertIn('id="total-geral"', html)
        self.assertIn('id="avisos"', html)
        # sem JavaScript o formulario continua funcionando
        self.assertIn('action="/aprovacoes/100/horas"', html)

    def test_sessao_expirada_em_clique_manda_para_o_login(self):
        resposta = self.cliente.post(
            "/aprovacoes/100/horas", data={"valor": "Aprovado"}, headers={"HX-Request": "true"}
        )
        self.assertEqual(resposta.status_code, 401)
        self.assertTrue(resposta.headers["HX-Redirect"].endswith("/login"))
        self.assertEqual(self.repo.gravacoes, [])

    def test_sem_htmx_o_comportamento_antigo_segue(self):
        resposta = self.cliente.post("/aprovacoes/100/horas", data={"valor": "Aprovado"})
        self.assertEqual(resposta.status_code, 302)


if __name__ == "__main__":
    unittest.main(verbosity=2)
