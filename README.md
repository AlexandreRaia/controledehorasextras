# Controle de Horas Extras

Aplicação web em Flask para o controle diário de horas extras de motoristas,
usando PostgreSQL como banco de dados, com quatro tabelas: unidades,
funcionarios, usuarios e lancamentos.

## Quem pode fazer o quê

| Perfil | Lançar horas | Aprovar / rejeitar | Autorizar HC | Cadastros | Consultar |
|---|---|---|---|---|---|
| RH (Flávio Galisteu) | sim | não | não | não | sim |
| Gestor (Fernando Cruz) | não | sim | sim | não | sim |
| Operações (Veridiana) | não | não | não | não | sim |
| Administrador | não | não | não | sim | sim |

Duas travas garantem a separação de funções:

- O RH edita e exclui lançamentos até o fechamento do mês, decididos ou não.
  Editar um lançamento já decidido desfaz a decisão: ele volta para **Pendente**
  e o gestor decide de novo. O RH nunca grava Aprovado nem Rejeitado.
- O gestor grava apenas situação, hora corrida, parecer e a trilha de quem
  decidiu. Data, entrada, saída e funcionário nunca entram no payload dele.

O administrador mantém cadastros, mas não lança nem aprova, pela mesma razão.

## Fechamento do mês

Depois que as horas de um mês vão para a folha, ele é fechado, e nada mais
muda naquele período: ninguém lança, edita, exclui nem decide.

- **Quem fecha:** o Gestor, que atesta que o mês está completo. O sistema só
  aceita o fechamento quando não resta lançamento esperando decisão, seja de
  horas excedentes ou de hora corrida pedida. Dias sem excedente e sem pedido
  de hora corrida não impedem o fechamento.
- **Quem reabre:** só o Administrador, informando o motivo. Cada fechamento e
  cada reabertura ficam registrados na tabela `fechamentos`, com quem fez e
  quando, e a tela de Fechamento lista as reaberturas do ano.
- **Onde fica a trava:** dentro do repositório (`app/repo.py`), em toda criação,
  alteração e exclusão de lançamento. Assim nenhuma rota esquece de checar. As
  telas escondem os botões, mas a regra vale mesmo para uma requisição forjada.
- Não se fecha um mês que ainda não começou.

Quem pode fechar e reabrir está em `PODE_FECHAR` e `PODE_REABRIR`, em
`app/auth.py`.

## Cálculo

A permanência é a diferença entre saída e entrada. Saída menor que a entrada é
tratada como virada de meia-noite.

Da permanência sai a hora de almoço, que nunca conta como hora excedente. Ela é
descontada **quando a permanência passa de 6 horas** (`ALMOCO_A_PARTIR_HORAS`);
em um período mais curto não há almoço a descontar.

O excedente é o tempo líquido menos a jornada e **pode ser negativo**: quem
trabalha menos que a jornada fica devendo horas, e o dia aparece com excedente
negativo, sem o RH precisar digitar nada. As horas trabalhadas mostram só a
jornada normal, no máximo 8 horas.

A hora corrida é a exceção. Ela significa que a pessoa não parou para almoçar.
O RH marca o pedido no lançamento e **ela já vale desde aquele momento**: a hora
do almoço deixa de ser descontada e entra no excedente sem esperar o gestor. O
gestor ainda autoriza ou nega. Autorizada, nada muda. Negada, o sistema refaz o
cálculo e o desconto do almoço volta. Pendente e autorizada contam igual; só a
negativa devolve o desconto.

| Entrada | Saída | Permanência | Almoço | Trabalhadas | Excedentes | Sem HC (se negada) |
|---|---|---|---|---|---|---|
| 8:00 | 19:00, com HC | 11:00 | 0:00 | 8:00 | 3:00 | 2:00 |
| 8:00 | 19:00, sem HC | 11:00 | 1:00 | 8:00 | 2:00 | 2:00 |
| 8:00 | 17:00, sem HC | 9:00 | 1:00 | 8:00 | 0:00 | 0:00 |
| 8:00 | 16:30, sem HC | 8:30 | 1:00 | 7:30 | -0:30 | -0:30 |
| 10:00 | 17:00, sem HC | 7:00 | 1:00 | 6:00 | -2:00 | -2:00 |
| 10:00 | 17:00, com HC | 7:00 | 0:00 | 7:00 | -1:00 | -2:00 |
| 8:00 | 12:00, sem HC | 4:00 | 0:00 | 4:00 | -4:00 | -4:00 |

Faltas, abonos e outros casos que o sistema não prevê são corrigidos pelo RH no
campo Excedente do lançamento (veja "Ajuste do excedente pelo RH", abaixo).

A jornada e o almoço são configuráveis em `JORNADA_PADRAO_HORAS` e
`ALMOCO_HORAS`, iguais a 8 e 1 por padrão.

### Ajuste do excedente pelo RH

O sistema calcula o excedente sozinho, mas existem situações que ele não prevê.
No lançamento, o campo **Excedente (H:MM)** permite ao RH digitar o valor:

- **Em branco:** vale o cálculo. Na edição aparece "Calculado agora: ...".
- **Preenchido:** vale no lugar do cálculo e aceita valor **negativo**
  (por exemplo `-0:30`), para horas a compensar ou descontar. O limite é de
  20 horas, para mais ou para menos.
- **Motivo obrigatório:** o RH precisa preencher a Observação do RH.
- **Voltar ao cálculo:** apagar o campo e salvar. Digitar o mesmo valor que o
  sistema calculou também não conta como ajuste.

Cada lançamento guarda os dois valores: `excedidas_manual_seg` (o digitado, nulo
sem ajuste) e `excedidas_seg` (o que está em vigor). Listas, relatório e análise
mostram a etiqueta **Ajustado**, com o valor calculado e o motivo, e o CSV traz as
colunas "Excedente calculado" e "Ajustado pelo RH".

Valem as regras de sempre: editar devolve o lançamento ao gestor, e mês fechado
bloqueia tudo. A decisão do gestor sobre a hora corrida **não regrava** um
excedente ajustado. Um excedente diferente de zero, positivo ou negativo, exige
decisão do gestor antes do fechamento do mês.

### Plantonista 12x36

Cada funcionário tem uma **Jornada** no cadastro: 8 horas ou plantonista 12x36.
O plantonista trabalha 12 horas e folga 36, então o lançamento continua sendo
um por dia trabalhado, sem somar "um dia e meio".

- A jornada dele é de 12 horas e **não há hora de almoço** a descontar. Também
  não existe hora corrida para ele.
- O excedente é o que passa de 12 horas no plantão.
- Plantão feito no **dia de folga** (fora da escala) conta inteiro como excedente.
  O RH marca "Plantão no dia de folga" no lançamento. O sistema não deduz a folga
  sozinho, porque a escala pode ser trocada entre colegas.

| Entrada | Saída | Permanência | Trabalhadas | Excedentes |
|---|---|---|---|---|
| 7:00 | 19:00 | 12:00 | 12:00 | 0:00 |
| 7:00 | 20:30 | 13:30 | 12:00 | 1:30 |
| 7:00 | 19:00, na folga | 12:00 | 0:00 | 12:00 |

A jornada vale para todos os lançamentos do funcionário, inclusive os antigos:
mudar o cadastro recalcula o histórico. Quem já estava cadastrado fica com 8 horas.

Como o excedente depende da hora corrida, negá-la regrava a coluna
`excedidas_seg`. Essa é a única hora que o gestor move, e apenas como
consequência da própria decisão. Entrada, saída, data e funcionário continuam
intocados.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Preencha o `.env`:

```
DATABASE_URL=postgresql://controlehoras:SENHA@HOST:5432/controlehoras
SECRET_KEY=uma-chave-aleatoria-longa
```

O banco `controlehoras` pertence ao usuário `controlehoras`, que só tem acesso
a ele. O superusuário `postgres` fica fora do app.

## Preparar o banco

```bash
python -m tools.setup_db
```

Cria as tabelas que faltam e os quatro usuários iniciais, imprimindo as senhas
geradas uma única vez. Rodar de novo não apaga nada: tabelas e usuários
existentes são preservados. Use `--senhas` para gerar senhas novas para todos
ou `--so-tabelas` para mexer apenas no esquema.

O app também cria as tabelas sozinho na primeira conexão, então em uma
instalação nova basta rodar o script para ter os usuários de acesso.

| Tabela | Conteúdo |
|---|---|
| unidades | nome |
| funcionarios | nome, prontuário (único), telefone, cargo, unidade, ativo |
| usuarios | nome, login (único, sem diferenciar maiúsculas), hash da senha, perfil, ativo |
| lancamentos | funcionário, prontuário, data, entrada e saída em segundos, excedente, situação, hora corrida, observação do RH, parecer do gestor e a trilha de quem lançou e decidiu |

Situação, situação da hora corrida e perfil só aceitam os valores previstos,
garantido por `CHECK` no próprio banco.

## Executar

```bash
python run.py
```

A aplicação sobe em http://localhost:5000.

Em produção, use um servidor WSGI e desligue o modo debug:

```bash
pip install waitress
waitress-serve --port=5000 run:app
```

## Telas

A raiz do site não tem painel. Ela encaminha o gestor para a fila de
aprovações e os demais perfis para a lista de lançamentos.

- **Lançar o dia**: formulário para o RH registrar entrada e saída de um
  funcionário em uma data, com a opção de pedir hora corrida. Abre em uma janela
  (modal) sobre a lista de lançamentos.
- **Editar**: abre o mesmo formulário na janela, sem sair da lista. Ao salvar, só a
  lista é atualizada, com os mesmos filtros, e a página não recarrega. Sem
  JavaScript, os mesmos botões levam a uma página própria, e tudo continua
  funcionando.
- **Lançamentos**: lista do mês agrupada por funcionário, com subtotal de cada
  um e filtros por funcionário e situação.
- **Aprovações**: fila do gestor agrupada por funcionário. Cada linha tem os
  botões Aprovar e Reprovar para as horas excedentes e Autorizar e Negar para
  a hora corrida, que só aparecem quando o RH pediu. Um clique grava no banco
  na hora. A coluna
  Sem HC mostra no que o excedente ficaria se a hora corrida fosse negada.
  Os mesmos botões aparecem na lista de Lançamentos quando quem olha é o
  gestor. A decisão é sempre dia a dia, não há aprovação em lote.
- **Relatórios**: consolidado por funcionário, detalhe dia a dia e exportação
  em CSV separado por ponto e vírgula, pronto para o Excel.
- **Fechamento**: situação dos doze meses do ano, com o que ainda espera
  decisão, o botão de fechar para o Gestor e o de reabrir para o Administrador.
- **Cadastros**: unidades, funcionários e usuários.

Os botões do gestor atualizam só o bloco do funcionário, o aviso e o total
geral, sem recarregar a página nem perder a rolagem. Isso usa o htmx, que está
em `app/static/htmx.min.js` (versão 2.0.4, sem depender de CDN). Sem JavaScript
os mesmos formulários funcionam recarregando a página, e se a sessão expirou o
clique leva ao login.

## Testes

```bash
.venv\Scripts\python.exe -m unittest discover -s tests
```

Os testes usam um repositório em memória e não tocam no banco. O SQL do
repositório não é coberto por eles: foi conferido à mão contra um PostgreSQL real. Cobrem o
cálculo de horas, o login, as permissões de cada perfil e as duas travas de
separação de funções.

## Estrutura

```
app/
  db.py           pool de conexões com o PostgreSQL
  schema.py       criação das tabelas e nomes das colunas
  repo.py         leitura e escrita das quatro tabelas
  auth.py         sessão, perfis e decoradores de permissão
  utils.py        conversões de hora e data
  views/          rotas por assunto (lançamentos, aprovações, fechamento...)
  templates/      telas
tools/
  setup_db.py     criação das tabelas e usuários iniciais
tests/
run.py
```
