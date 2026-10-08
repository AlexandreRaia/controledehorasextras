# Controle de Horas Extras

Aplicação web em Flask para o controle diário de horas extras de motoristas,
usando o Baserow como banco de dados. As quatro tabelas existentes continuam
sendo a fonte da verdade: Unidades, Funcionarios, Usuarios e Lançamentos.

## Quem pode fazer o quê

| Perfil | Lançar horas | Aprovar / rejeitar | Autorizar HC | Cadastros | Consultar |
|---|---|---|---|---|---|
| RH (Flávio Galisteu) | sim | não | não | não | sim |
| Gestor (Fernando Cruz) | não | sim | sim | não | sim |
| Operações (Veridiana) | não | não | não | não | sim |
| Administrador | não | não | não | sim | sim |

Duas travas garantem a separação de funções:

- O RH só altera ou exclui um lançamento enquanto ele está **Pendente**. Depois
  da decisão do gestor, a tela de edição é bloqueada.
- O gestor grava apenas situação, hora corrida, parecer e a trilha de quem
  decidiu. Data, entrada, saída e funcionário nunca entram no payload dele.

O administrador mantém cadastros, mas não lança nem aprova, pela mesma razão.

## Cálculo

A permanência é a diferença entre saída e entrada. Saída menor que a entrada é
tratada como virada de meia-noite.

Da permanência sai a hora de almoço, que nunca conta como hora excedente. O
desconto não derruba a jornada abaixo do padrão, então quem fica oito horas e
meia não aparece devendo meia hora. O excedente é o que sobra acima da jornada.

A hora corrida é a exceção. Ela significa que a pessoa não parou para almoçar.
O RH marca o pedido no lançamento e o gestor autoriza ou nega. Autorizada, a
hora do almoço deixa de ser descontada e passa a contar como excedente. Negada,
o desconto permanece.

| Entrada | Saída | Permanência | Almoço | Trabalhadas | Excedentes | Com HC |
|---|---|---|---|---|---|---|
| 8:00 | 19:30 | 11:30 | 1:00 | 10:30 | 2:30 | 3:30 |
| 8:00 | 16:30 | 8:30 | 0:30 | 8:00 | 0:00 | 0:30 |
| 8:00 | 12:00 | 4:00 | 0:00 | 4:00 | 0:00 | 0:00 |

A jornada e o almoço são configuráveis em `JORNADA_PADRAO_HORAS` e
`ALMOCO_HORAS`, iguais a 8 e 1 por padrão.

Como o excedente depende da hora corrida, a decisão do gestor regrava a coluna
`Horas Excedidas`. Essa é a única hora que ele move, e apenas como consequência
da própria decisão. Entrada, saída, data e funcionário continuam intocados.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Preencha o `.env`:

```
BASEROW_URL=https://api.baserow.io
BASEROW_EMAIL=seu-email-do-baserow
BASEROW_PASSWORD=sua-senha-do-baserow
SECRET_KEY=uma-chave-aleatoria-longa
```

O e-mail e a senha do Baserow são necessários porque o app lê o esquema das
tabelas e cria os campos que faltam. Se preferir, gere também um token de banco
de dados em Settings e coloque em `BASEROW_TOKEN`: ele passa a ser usado para
ler e gravar linhas.

## Conferir a conexão

```bash
python -m tools.diagnostico
```

Mostra se a instância responde, se o token tem permissão nas tabelas, se o
e-mail e a senha autenticam, quais tabelas foram encontradas, quais campos já
existem e quais ainda faltam. Também imprime os IDs prontos para colar no
`.env`. Rode isso antes de qualquer outra coisa.

O token de banco de dados precisa das quatro permissões marcadas. No Baserow,
abra a foto do perfil, Settings, Database tokens, clique no token e habilite
Create, Read, Update e Delete para o banco de dados.

## Preparar o Baserow

```bash
python -m tools.setup_baserow --senhas
```

O script localiza as tabelas pelo nome, cria os campos que o app precisa e
cadastra os quatro usuários iniciais, imprimindo as senhas geradas uma única
vez. Rode sem `--senhas` para preservar as senhas já definidas.

Campos criados automaticamente:

- **Funcionarios**: Ativo
- **Usuarios**: Login, SenhaHash, Perfil
- **Lançamentos**: Status, HC Status, Observacao RH, Parecer Gestor, Unidade,
  Lancado Por, Lancado Em, Decidido Por, Decidido Em

Colunas que já existiam são reaproveitadas, não duplicadas: `Data`, `HC` como
pedido de hora corrida, `Aprovacao` mantida em sincronia com o novo `Status` e
`Horas Trabalhadas` como fórmula do próprio Baserow.

O campo `Senha` que já existe em Usuarios é do tipo password do Baserow e não
pode ser lido pela API. O app não o utiliza. A autenticação usa `SenhaHash`,
gravado com hash do Werkzeug.

Se as tabelas não forem encontradas pelo nome, informe os IDs no `.env`
(`TABLE_UNIDADES`, `TABLE_FUNCIONARIOS`, `TABLE_USUARIOS`, `TABLE_LANCAMENTOS`).
O ID aparece na URL do Baserow ao abrir a tabela.

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

- **Lançar o dia**: grade com todos os motoristas ativos para o RH preencher
  entrada e saída de uma vez. Linhas em branco são ignoradas e lançamentos já
  decididos ficam travados.
- **Lançamentos**: lista do mês agrupada por funcionário, com subtotal de cada
  um e filtros por funcionário e situação.
- **Aprovações**: fila do gestor agrupada por funcionário. Cada linha tem os
  botões Aprovar e Reprovar para as horas excedentes e os polegares verde e
  vermelho para a hora corrida. Um clique grava no Baserow na hora. A coluna
  Com HC mostra no que o excedente ficaria se a hora corrida fosse autorizada.
  Os mesmos botões aparecem na lista de Lançamentos quando quem olha é o
  gestor. Há também decisão em lote para resolver vários dias de uma vez.
- **Relatórios**: consolidado por funcionário, detalhe dia a dia e exportação
  em CSV separado por ponto e vírgula, pronto para o Excel.
- **Cadastros**: unidades, funcionários e usuários.

## Testes

```bash
.venv\Scripts\python.exe -m unittest discover -s tests
```

Os testes usam um repositório em memória e não tocam no Baserow. Cobrem o
cálculo de horas, o login, as permissões de cada perfil e as duas travas de
separação de funções.

## Estrutura

```
app/
  baserow.py      cliente HTTP da API do Baserow
  schema.py       nomes de tabelas e campos, criação do que falta
  repo.py         leitura e escrita das quatro tabelas
  auth.py         sessão, perfis e decoradores de permissão
  utils.py        conversões de hora e data
  views/          rotas por assunto
  templates/      telas
tools/
  setup_baserow.py  preparação do banco e usuários iniciais
tests/
run.py
```
