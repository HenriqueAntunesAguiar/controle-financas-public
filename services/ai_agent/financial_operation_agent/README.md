# Financial Operation Agent

Agente responsável exclusivamente por criar, atualizar e remover lançamentos
financeiros solicitados explicitamente pelo usuário.

## Ferramentas

- `get_expense_by_id`: consulta o lançamento atual antes de atualizar ou remover;
- `create_expense`: cria um lançamento manual;
- `update_expense`: atualiza integralmente um lançamento existente;
- `delete_expense`: realiza sua remoção lógica.

Cada ferramenta possui seu próprio módulo principal:

```text
tools/
├── create_expense/
│   └── tool.py
├── update_expense/
│   └── tool.py
└── delete_expense/
    └── tool.py
```

`FinancialOperationAgent()` cria por padrão o reader, o repositório PostgreSQL e
os handlers do `CashFlowUseCases`, reutiliza `get_expense_by_id` e monta um
`StateGraph` explícito com os nós `model`, `approval` e `tools`. Testes ainda podem
injetar explicitamente reader e handlers alternativos.

```python
component = FinancialOperationAgent()

manager = create_ai_manager_agent()
```

O AI Manager registra `FinancialOperationAgent(checkpointer=None).as_tool()` por
padrão. Nesse modo, o checkpointer pertence ao Manager e preserva a execução do
HITL. Uma tool explicitamente injetada com o nome `financial_operation_agent`
substitui a composição padrão para testes.

Para testes ou benchmarks sem um agente chamador:

```python
agent = component.as_agent()
result = agent.invoke({"messages": [{"role": "user", "content": request}]})
```

## Execução manual

O runner interativo executa o agente diretamente, registra somente no Langfuse
quando habilitado e persiste o estado do HITL no PostgreSQL:

```powershell
cd services/ai_agent
.\.venv\Scripts\python.exe -m financial_operation_agent.tests.test_run
```

O runner reutiliza o `CashFlowUseCases` e o repositório PostgreSQL do
`invoice_web`, mas desabilita sua auditoria local nesse teste. Portanto, escolher
`approve` executa a alteração real no banco configurado. Escolher `reject` retoma
o agente sem executar a escrita.

## Aprovação humana

As três ferramentas de escrita passam pelo nó `approval`. Quando o modelo
solicita uma alteração, esse nó chama `langgraph.types.interrupt`, persiste o
estado e interrompe a execução antes de encaminhar a chamada ao nó `tools`. A
ferramenta de leitura segue diretamente para `tools`, sem aprovação. O payload
da interrupção contém os argumentos e uma descrição como:

```text
Irei adicionar o seguinte lançamento:
mês: julho
ano: 2026
nome: parcela carro
valor: 12.00
categoria: carro
meio de pagamento: debito
tipo: actual
recorrência: none

Confirma esta alteração?
```

O cliente deve exibir essa descrição e retomar a mesma thread com uma decisão:

```python
from langgraph.types import Command

result = manager.invoke(request, config=thread_config)
interrupt = result["__interrupt__"][0]

result = manager.invoke(
    Command(resume={
        interrupt.id: {"decisions": [{"type": "approve"}]},
    }),
    config=thread_config,
)
```

Para rejeitar:

```python
Command(resume={
    interrupt.id: {
        "decisions": [{
            "type": "reject",
            "message": "Não quero realizar essa alteração.",
        }]
    }
})
```

A retomada deve reutilizar o mesmo `thread_id`. O checkpointer PostgreSQL pertence
ao agente principal que recebe `financial_operation_agent` como tool e mantém o
estado de toda a execução enquanto a decisão é aguardada.
