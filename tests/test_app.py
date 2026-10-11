"""Testes do calculo de horas e das regras de permissao, sem tocar no banco."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, set_repo  # noqa: E402
from app import schema as S  # noqa: E402
from app.auth import hash_senha  # noqa: E402
from app.config import Config  # noqa: E402
from app.repo import MesFechado  # noqa: E402
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
            hc_autorizada=hc,
        )

    def test_almoco_sai_do_excedente(self):
        perm, almoco, trab, exced = self.jornada("8:00", "19:30")
        self.assertEqual(format_duration(perm), "11:30")
        self.assertEqual(format_duration(almoco), "1:00")
        self.assertEqual(format_duration(trab), "10:30")
        self.assertEqual(format_duration(exced), "2:30")

    def test_hora_corrida_devolve_a_hora_do_almoco(self):
        _, almoco, trab, exced = self.jornada("8:00", "19:30", hc=True)
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "11:30")
        self.assertEqual(format_duration(exced), "3:30")

    def test_desconto_nunca_derruba_abaixo_da_jornada(self):
        # Quem fica 8:30 nao pode aparecer devendo meia hora.
        _, almoco, trab, exced = self.jornada("8:00", "16:30")
        self.assertEqual(format_duration(almoco), "0:30")
        self.assertEqual(format_duration(trab), "8:00")
        self.assertEqual(exced, 0)
        # Com hora corrida, a meia hora a mais vira excedente.
        _, _, _, exced_hc = self.jornada("8:00", "16:30", hc=True)
        self.assertEqual(format_duration(exced_hc), "0:30")

    def test_jornada_curta_nao_desconta_almoco(self):
        _, almoco, trab, exced = self.jornada("8:00", "12:00")
        self.assertEqual(almoco, 0)
        self.assertEqual(format_duration(trab), "4:00")
        self.assertEqual(exced, 0)

    def test_sem_excedente_dentro_da_jornada(self):
        _, _, trab, exced = self.jornada("8:00", "15:00")
        self.assertEqual(format_duration(trab), "7:00")
        self.assertEqual(exced, 0)

    def test_virada_de_meia_noite(self):
        perm, _, trab, exced = self.jornada("22:00", "6:00")
        self.assertEqual(format_duration(perm), "8:00")
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
            "unidade": "Detran", "unidade_ids": [18], "ativo": True,
        }, {
            "id": 27, "nome": "Anderson", "prontuario": "48906",
            "telefone": "(11)914127164", "cargo": "Motorista",
            "unidade": "Detran", "unidade_ids": [18], "ativo": True,
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
            "hash": hash_senha("senha123"), "ativo": True, "notas": "",
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
            "trabalhadas_seg": trab, "excedidas_seg": exced,
            "excedidas_com_hc_seg": exced_hc,
            "status": status, "hc_solicitada": True, "hc_status": "Pendente",
            "obs_rh": "", "parecer": "", "unidade": "Detran",
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
                        and ((i["excedidas_seg"] or 0) > 0 or i["hc_solicitada"])) \
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
        self.assertEqual(self.cliente.get("/lancamentos/dia").status_code, 403)

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


class TestSeparacaoDeFuncoes(BaseWeb):
    def test_rh_nao_edita_lancamento_ja_decidido(self):
        self.entrar("flavio")
        resposta = self.cliente.get("/lancamentos/101/editar", follow_redirects=True)
        self.assertIn("ja analisado pelo gestor", resposta.get_data(as_text=True).lower())
        self.assertEqual(self.repo.gravacoes, [])

    def test_rh_nao_exclui_lancamento_ja_decidido(self):
        self.entrar("flavio")
        self.cliente.post("/lancamentos/101/excluir", follow_redirects=True)
        self.assertEqual(self.repo.gravacoes, [])

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
        # O RH nao decide: Status e parecer nao podem ir no payload.
        self.assertNotIn(S.F["lanc_status"], payload)
        self.assertNotIn(S.F["lanc_parecer"], payload)
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

    def test_autorizar_hc_recalcula_o_excedente(self):
        self.entrar("fernando")
        antes = self.repo.lancamento(100)
        self.cliente.post("/aprovacoes/100", data={
            "decisao": "Aprovado", "hc_decisao": "Autorizada", "parecer": "nao almocou",
        }, follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Autorizada")
        # A hora do almoco volta para o excedente: 2:30 vira 3:30.
        self.assertEqual(antes["excedidas_seg"], 2 * 3600 + 1800)
        self.assertEqual(payload[S.F["lanc_excedidas"]], 3 * 3600 + 1800)

    def test_negar_hc_mantem_o_excedente(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100", data={
            "decisao": "Aprovado", "hc_decisao": "Negada", "parecer": "almocou",
        }, follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Negada")
        self.assertNotIn(S.F["lanc_excedidas"], payload)

    def test_rejeicao_exige_parecer(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100", data={"decisao": "Rejeitado", "parecer": ""})
        self.assertEqual(self.repo.gravacoes, [])


class TestTelas(BaseWeb):
    def test_telas_de_consulta_renderizam(self):
        self.entrar("flavio")
        for rota in ("/", "/lancamentos/", "/lancamentos/dia", "/relatorios"):
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

    def test_autorizar_hc_na_linha_recalcula(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Autorizada"},
                          follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Autorizada")
        self.assertEqual(payload[S.F["lanc_excedidas"]], 3 * 3600 + 1800)
        # Decidir a hora corrida nao decide as horas excedentes.
        self.assertNotIn(S.F["lanc_status"], payload)

    def test_negar_hc_na_linha(self):
        self.entrar("fernando")
        self.cliente.post("/aprovacoes/100/hc", data={"valor": "Negada"},
                          follow_redirects=True)
        _, _, payload = self.repo.gravacoes[-1]
        self.assertEqual(payload[S.F["lanc_hc_status"]], "Negada")
        self.assertNotIn(S.F["lanc_excedidas"], payload)

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
        # 8:00 as 20:00 = 12h de permanencia, menos 1h de almoco, menos 8h
        self.assertEqual(payload[S.F["lanc_excedidas"]], 3 * 3600)
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

    def test_lote_preserva_mes_fechado(self):
        self.fecha_outubro()
        self.como("fernando")
        resposta = self.cliente.post(
            "/aprovacoes/lote", data={"decisao": "Rejeitado", "parecer": "x", "selecionados": ["100", "102"]},
            follow_redirects=True,
        )
        self.assertIn("preservados", resposta.get_data(as_text=True))
        self.assertEqual(self.repo.gravacoes, [])

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

    def test_grade_do_dia_recusa_mes_fechado(self):
        self.fecha_outubro()
        self.como("flavio")
        self.cliente.post("/lancamentos/dia", data={"data": "2026-10-20", "entrada_27": "8:00", "saida_27": "17:00"})
        self.assertEqual(self.repo.gravacoes, [])

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
