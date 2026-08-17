# Agentes financeiros

Este serviço concentra a orquestração, os modelos, as ferramentas, a memória e
os guardrails do assistente financeiro usado pela aplicação FastAPI.

## Componentes

![Fluxo do AI Manager, agentes especializados, ferramentas e HITL](../../doc_images/controle-financas%20(2).jpg)

```text
AI Manager
  |-- Financial Data Agent       consultas e comparações
  `-- Financial Operation Agent  criação, atualização e remoção com HITL

Infraestrutura compartilhada
  |-- guardrails/       classificação de entrada e reserva de saída
  |-- memory/           checkpointer PostgreSQL e resumo de conversa
  |-- model_providers/  construção dos modelos
  `-- observability/    integração opcional com Langfuse
```

O AI Manager é criado com `create_ai_manager_agent()`. Ele aplica guardrail
semântico de entrada, máscara para números de cartão e sumariza conversas longas.
Os dois agentes especializados são registrados como tools.

## Modelos

Os nomes dos modelos ficam centralizados em `model_providers/llm.py`. Atualmente
Manager, sumarização, agentes especializados e classificador usam modelos OpenAI.
A chave é lida de `OPENAI_API_KEY`.

## Memória

`memory/checkpoint.py` cria um `PostgresSaver` compartilhado. Cada conversa deve
usar um `thread_id` estável em:

```python
config = {"configurable": {"thread_id": thread_id}}
```

O mesmo identificador deve ser reutilizado ao retomar um interrupt do HITL.
`POSTGRES_CHECKPOINT_DSN` pode fornecer uma conexão exclusiva; sem ele, são
usadas as variáveis `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` e `POSTGRES_PASSWORD`.

## Human-in-the-loop

O agente operacional usa um `StateGraph` explícito. Chamadas de
`create_expense`, `update_expense` e `delete_expense` passam pelo nó `approval`,
que chama `interrupt()` antes de qualquer escrita. `get_expense_by_id` é uma
consulta e segue diretamente para o nó `tools`.

O cliente retoma a execução com:

```python
Command(resume={
    interrupt.id: {
        "decisions": [{"type": "approve"}],
    }
})
```

Uma rejeição remove a chamada pendente e devolve um `ToolMessage` ao modelo sem
executar o handler.

## Decisões arquiteturais

### Divisão entre agentes

Seria possível criar um único agente para conversar com o usuário, consultar,
analisar e modificar os dados. Entretanto, concentrar todas essas
responsabilidades aumenta a quantidade de ferramentas e regras que o modelo
precisa considerar em cada decisão. O projeto adota uma arquitetura com um
orquestrador e dois agentes especializados para reduzir esse escopo por chamada.

Nos protótipos deste projeto, a separação melhorou a previsibilidade das escolhas
de ferramentas e reduziu o contexto enviado a cada agente, com o custo de uma
etapa adicional de roteamento e, consequentemente, maior latência.

#### AI Manager

O AI Manager é o ponto de entrada da conversa. Ele responde interações gerais,
como saudações, preserva o contexto e identifica quando deve encaminhar uma
tarefa para um agente especializado. Ele não executa diretamente consultas ou
alterações financeiras.

#### Financial Data Agent

O Financial Data Agent consulta o banco e responde perguntas analíticas. Sempre
que um resultado puder ser calculado deterministicamente, a responsabilidade
fica em uma ferramenta Python, e não no raciocínio livre do modelo.

Por exemplo, uma conclusão como:

> A fatura diminuiu R$ 300,00, enquanto a categoria carro apresentou redução
> de 30%.

exige totais, diferenças e percentuais consistentes entre dois períodos. A
ferramenta
`financial_data_agent/tools/compare_monthly_values` realiza esses cálculos,
classifica aumentos e reduções e compara as categorias. O agente seleciona os
argumentos corretos e explica o resultado estruturado, sem recalculá-lo. Isso
reduz o risco de valores inconsistentes e torna a regra testável.

#### Financial Operation Agent

O Financial Operation Agent concentra as mutações: criação, atualização e
remoção lógica de lançamentos. Ele também pode consultar um lançamento por ID
para apresentar o estado atual antes de atualizá-lo ou removê-lo, mas não é
responsável por consultas analíticas.

As operações de escrita passam pelo HITL. O agente estrutura os dados fornecidos
pelo usuário nos argumentos da tool, e o nó `approval` do LangGraph chama
`interrupt()` antes de executar o handler. O frontend apresenta essa prévia no
chat e envia a decisão humana.

Com `approve`, o grafo recupera o checkpoint da mesma thread e encaminha a
chamada ao nó `tools`. Com `reject`, a ferramenta não é executada e o fluxo volta
ao modelo com uma mensagem de rejeição.

#### Financial Data Agent versus Financial Operation Agent

A separação entre leitura e escrita oferece três benefícios principais:

1. **Responsabilidade delimitada:** cada agente recebe somente as ferramentas e
   regras necessárias ao seu tipo de tarefa.
2. **Evolução da infraestrutura:** atualmente os dois agentes usam o mesmo
   PostgreSQL, mas a separação permite direcionar consultas a réplicas de leitura
   e manter mutações no banco primário se a carga futura justificar essa
   arquitetura.
3. **Segurança proporcional ao risco:** leituras também exigem controle de acesso
   e privacidade, mas criações, atualizações e exclusões demandam proteções
   adicionais, como tools restritas, validação de argumentos e HITL.

#### Disponibilização dos agentes ao AI Manager

Neste projeto, os agentes especializados são disponibilizados ao AI Manager por
tool calling dentro do mesmo processo. Essa solução preserva contratos claros
sem introduzir infraestrutura de comunicação adicional.

Em uma arquitetura distribuída, os agentes ou suas ferramentas poderiam ser
expostos por protocolos como MCP ou A2A para permitir escalabilidade independente
e reutilização por outros sistemas. Para o escopo atual, essa separação seria
complexidade operacional sem benefício proporcional.

## Execução e testes

O serviço normalmente roda dentro do container `web`. Para testes locais:

```powershell
Set-Location .\services\ai_agent
.\.venv\Scripts\python.exe -m unittest discover -v
```

Os runners `tests/test_run.py` dos agentes são interativos e podem executar
consultas ou alterações contra o PostgreSQL configurado. No agente operacional,
`approve` efetua a escrita real.

## Observabilidade

Langfuse é desativado por padrão. Para habilitá-lo:

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

Falha ou ausência dessa configuração não deve impedir a execução do agente. Ao
ser habilitado, o callback recebe eventos de agentes, modelos e ferramentas;
mantenha-o desativado quando esses traces não puderem sair da máquina.
