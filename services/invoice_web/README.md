# Fatura Local - FastAPI em arquitetura hexagonal

A aplicacao FastAPI extrai PDFs e persiste os dados financeiros localmente. O
chat, quando utilizado, chama modelos OpenAI; a observabilidade dos agentes pode
enviar traces ao Langfuse quando for explicitamente habilitada.

Local no monorepo: `services/invoice_web/`.

```text
services/invoice_web/
|- Dockerfile
|- requirements.txt
|- run_web.py
|- tests/
`- fastapi_app/
|- domain/                    regras e tipos sem framework
|- application/
|  |- ports/                  contratos de entrada e saida
|  `- invoice_use_cases.py    casos de uso
|- adapters/
|  |- inbound/http/           controller FastAPI
|  `- outbound/
|     |- filesystem/          arquivos privados e JSON de versao
|     |- observability/       auditoria JSON sanitizada
|     |- pdf/                 extracao com pdfplumber
|     `- persistence/         SQLite e PostgreSQL
|- infrastructure/            configuracao e composition root
|- views/                     HTML, CSS e JavaScript
   `- main.py                 seguranca e inicializacao HTTP
```

## Executar

```powershell
docker compose up -d --build
```

Execute o comando a partir da raiz do repositorio, onde esta o
`docker-compose.yml`.

Para executar os testes localmente:

```powershell
Set-Location .\services\invoice_web
..\..\.venv\Scripts\python -B -m unittest tests.test_fastapi_app -v
```

Acesse `http://127.0.0.1:5000`.

O chatbot usa o AI Manager de `services/ai_agent`. No Docker, as credenciais
OpenAI e Langfuse sao carregadas de `services/ai_agent/.env`; a conexao com o
PostgreSQL e sobrescrita pelo Compose para usar o servico `db`.

## Ambiente de demonstracao

Para iniciar a aplicacao com volumes isolados e dados ficticios:

```powershell
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

O seed cria uma fatura importada de agosto de 2026, transacoes categorizadas,
resumo mensal e alguns lancamentos de fluxo de caixa. Os dados reais permanecem
nos volumes originais. Para voltar ao ambiente normal:

```powershell
docker compose up -d --build
```

Os volumes de demonstracao se chamam `controle_financas_demo_postgres` e
`controle_financas_demo_private`.

## Assistente financeiro

- `POST /api/assistant/chat`: envia uma mensagem com `thread_id` UUID.
- `POST /api/assistant/chat/decision`: aprova ou rejeita uma alteracao pendente.
- O AI Manager e criado apenas na primeira mensagem e reutilizado pelo processo.
- O historico e os interrupts do human-in-the-loop usam o checkpointer
  persistente no PostgreSQL.
- Consultas seguem para o Financial Data Agent. Criacao, atualizacao e exclusao
  seguem para o Financial Operation Agent e so executam depois da confirmacao.
- Quando habilitado no `.env`, o callback do Langfuse recebe eventos das
  chamadas dos agentes, modelos e ferramentas. Mantenha-o desativado se esses
  traces nao puderem sair da maquina.

O nome informado identifica a fatura no historico local e na tabela
`financeiro.documentos_fatura`. O PDF fica em `private/uploads/`. Cada processamento cria um JSON estruturado local
em `private/processed/` e uma nova versao no SQLite. A importacao manual grava
essa versao no schema `financeiro` do PostgreSQL.

As transacoes importadas preservam uma descricao curta do estabelecimento,
como `AMAZON BR`, removendo a notacao de parcela. Essa descricao permanece
somente no JSON local e no PostgreSQL e nunca e incluida nos logs tecnicos.

O parser usa as coordenadas das colunas do PDF, ignora a secao de parcelas
futuras e compara a soma extraida com `Total dos lancamentos atuais`. Uma
divergencia marca a versao como `needs_review` e impede a importacao.
Depois da conferencia manual do JSON, o botao `Aprovar revisao` libera
explicitamente essa versao para importacao.

`descricao` preserva o texto reconhecido na fatura. O campo derivado
`descricao_normalizada` remove acentos, consolida espacos e e persistido em
maiusculas. O identificador HMAC do estabelecimento usa uma chave textual
estavel independente dessa apresentacao, evitando a troca de IDs antigos.

## Categorizacao e dashboard

A interface lista somente transacoes da versao mais recente de cada fatura
importada. Uma categoria pode ser confirmada para uma transacao ou definida como
padrao do estabelecimento. Confirmacoes humanas ficam disponiveis na view
`spend_label.exemplos_treinamento`; previsoes nao confirmadas permanecem apenas
como sugestoes.

O dashboard usa uma unica fatura-base: a versao importada com a data de
referencia mais recente. Todas as transacoes dessa fatura formam o total do
mes-base, inclusive creditos. Nos meses seguintes entram somente compras
parceladas, repetidas pelo valor da parcela ate `total_parcelas`. O seletor de
horizonte limita quantos meses, contando o mes-base, aparecem na projecao.
Gastos recorrentes ativos entram a partir do mes seguinte. Regras sem prazo
ocupam todo o horizonte; regras com prazo incluem o mes final informado. Quando
a transacao de origem tambem e parcelada, a recorrencia prevalece para impedir
que o mesmo valor seja projetado duas vezes.

- `GET /api/categories`: categorias ativas.
- `POST /api/categories`: cria ou reativa uma categoria informada pelo usuario.
- `GET /api/transactions`: transacoes categorizaveis.
- `PUT /api/transactions/{id}/category`: confirmacao manual.
- `PUT /api/transactions/{id}/recurrence`: ativa, limita ou remove recorrencia.
- `GET /api/merchants`: estabelecimentos canonicos.
- `POST /api/aliases/{hash}/merge`: uniao de aliases.
- `GET /api/analytics/monthly`: totais mensais por categoria.
- `GET|POST /api/cash-flow/expenses`: lista e cria gastos reais ou previstos,
  incluindo cartao de credito e outros meios de pagamento.
- `DELETE /api/cash-flow/expenses/{id}`: remove logicamente um lancamento.
- `PUT /api/cash-flow/expenses/{id}`: edita todos os dados e substitui a
  recorrencia ativa do lancamento, preservando seu historico.
- `PUT /api/cash-flow/expenses/{id}/recurrence`: altera a recorrencia do lancamento.
- `GET|POST /api/cash-flow/card-forecasts`: compatibilidade com clientes antigos;
  opera sobre lancamentos previstos no cartao no modelo unificado.
- `DELETE /api/cash-flow/card-forecasts/{id}`: compatibilidade para remover uma
  previsao de cartao.
- `GET|PUT /api/cash-flow/monthly/{mes}`: consulta e salva rendimento/guardado.
- `POST /api/cash-flow/monthly/{mes}/apply-result`: aplica o resultado ao guardado.

A listagem de transacoes aceita os filtros `q`, `category` e `status`, alem de
`sort` e `direction` para ordenacao. Os estados disponiveis sao `all`, `pending`,
`confirmed` e `suggested`.

O Chart.js 4.5.1 esta versionado em `static/vendor` e e servido localmente. O
navegador nao consulta CDN para renderizar o grafico.

O grafico aceita `include_card` e `include_manual` para exibir ou ocultar cada
origem, alem de `include_actual` e `include_projected` para separar gastos reais
de previstos. O parametro `include_expense_income`, desativado por padrao, adiciona a
linha de entrada/saida do guardado (`rendimento - gastos`): um valor positivo
entra no guardado e um valor negativo sai dele, alem do saldo projetado iniciado
em `guardado_base` e atualizado cumulativamente com cada resultado mensal. O
ultimo rendimento cadastrado
se repete nos meses futuros ate que um novo valor mensal seja informado.
Na interface, `Saldo mensal` e `Saldo acumulado` sao filtros independentes;
ambos ficam ocultos por padrao e podem ser exibidos separadamente ou juntos.
O painel lateral compara rendimento e gastos e mostra o total guardado acumulado
ao longo do horizonte selecionado, substituindo o antigo grafico de pizza.
Esse painel oferece uma simulacao opcional de juros compostos mensais. A formula
aplicada e `saldo_anterior * (1 + taxa_mensal) + resultado_do_mes`; a simulacao
nao altera valores persistidos e exibe o saldo final e os juros acumulados.
O detalhamento mensal permite selecionar um mes, comparar os totais por categoria
e abrir uma categoria para listar cada lancamento real ou projetado que compoe o
valor. O filtro de origem mostra todas as fontes por padrao e permite isolar
`Cartao` ou `Outros meios`. Um segundo filtro isola lancamentos reais ou
previstos. Os dados sao fornecidos por
`GET /api/analytics/monthly/{mes}/breakdown`.
O formulario unico seleciona por padrao um gasto real. Ele permite marcar o
lancamento como `actual` (compromisso confirmado) ou `planned` (lancamento
ficticio/simulado), escolher cartao, PIX, debito, dinheiro, transferencia ou
outro meio e configurar ocorrencia unica, infinita ou finita. O tipo independe
do mes: parcelas e recorrencias confirmadas continuam reais mesmo no futuro.
Cada alteracao de recorrencia encerra a configuracao anterior e preserva seu
historico no schema `cash_flow`. Previsoes permanecem separadas dos compromissos
confirmados e so entram nos graficos quando o filtro correspondente e ativado.
O resultado mensal e `rendimento - gastos`; o
total guardado e `guardado_base + resultado_aplicado`.
A reaplicacao substitui o resultado anteriormente aplicado, evitando soma dupla.
No painel de rendimento e guardado, o filtro de gastos permite comparar o
resultado com `Cartao + outros lancamentos` ou com `Somente cartao`. O segundo
modo e apenas uma simulacao: mostra `guardado_base + resultado` e impede aplicar
esse valor ao guardado.

As tabelas de aprendizado pertencem ao schema `spend_label`, separado dos dados
originais da fatura no schema `financeiro`. O servico de execucao unica
`db_schema_setup` aplica, em ordem, as migracoes de `financeiro`, `spend_label` e
`cash_flow` antes do inicio da aplicacao web.

## Observabilidade local

- `GET /health/live`: informa se o processo web responde, sem testar bancos.
- `GET /health/ready`: testa SQLite, armazenamento privado e PostgreSQL; retorna
  `503` quando algum componente esta indisponivel.
- `GET /api/system/connections`: mostra estado, codigo sanitizado e latencia de
  cada conexao.
- `GET /api/system/logs?limit=50`: mostra os eventos JSON recentes.
- Arquivo local: `private/logs/application.jsonl`.

Os logs usam uma lista fechada de campos. Senha do PDF, nome do arquivo,
descricao, estabelecimento, valores, conteudo extraido e credenciais do banco
nao sao registrados. `X-Request-ID` permite correlacionar uma resposta HTTP com
o respectivo evento local.

Para acompanhar os eventos no PowerShell:

```powershell
Get-Content .\private\logs\application.jsonl -Wait
```
