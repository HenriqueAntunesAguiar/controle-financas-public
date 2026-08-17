# Financial Data Agent

O Financial Data Agent responde perguntas financeiras usando ferramentas de
consulta somente leitura. O modelo de IA interpreta a intenção do usuário e
apresenta os resultados, mas não é responsável por calcular valores financeiros.

## Responsabilidades

O processamento é dividido da seguinte forma:

1. A IA identifica os meses, a origem dos valores e a natureza dos dados
   solicitados (`actual`, `projected` ou `actual_and_projected`).
2. A ferramenta valida esses argumentos e solicita os dados ao repositório.
3. O adaptador PostgreSQL consulta os registros necessários.
4. O código Python calcula totais, diferenças, percentuais, direções e variações
   por categoria.
5. A IA explica o resultado retornado pela ferramenta sem recalculá-lo.

```text
Pergunta do usuário
        ↓
Interpretação da IA
        ↓
Ferramenta financeira
        ↓
Consulta PostgreSQL e cálculo determinístico em Python
        ↓
Apresentação do resultado pela IA
```

## Comparação entre meses

Perguntas sobre aumento, redução, diferença ou variação entre dois meses devem
usar `compare_monthly_values`.

A IA é responsável somente por selecionar corretamente:

- `previous_month`;
- `current_month`;
- `source`;
- `data_kind`;
- `limit`.

A ferramenta realiza deterministicamente:

- seleção dos valores da mesma origem nos dois períodos;
- diferença entre o total atual e o anterior;
- variação percentual;
- classificação como aumento, redução ou valor inalterado;
- comparação consolidada por categoria;
- ordenação das maiores variações;
- detalhamento das categorias por origem;
- identificação de dados ausentes ou períodos não comparáveis.

O resultado matemático retornado pela ferramenta é a fonte de verdade. A IA não
deve estimar, corrigir ou recalcular esses valores. Sua margem de interpretação
fica restrita à escolha dos argumentos e à explicação fundamentada do resultado.

## Componentes atuais

- `agent.py`: a classe `FinancialDataAgent` conecta reader, ferramentas, modelo
  e prompt e disponibiliza a mesma instância como agente ou como tool.
- `tools/get_monthly_values/tool.py`: implementação principal da ferramenta de
  consulta mensal.
- `tools/get_monthly_values/result.py`: transformação determinística do retorno
  da consulta em resultado estruturado.
- `tools/get_expense_by_id/tool.py`: consulta unitária de um lançamento manual
  ativo pelo ID.
- `tools/get_expense_by_id/result.py`: normaliza o contrato de item encontrado
  ou inexistente sem expor detalhes do PostgreSQL.
- `tools/compare_monthly_values/tool.py`: implementação principal da ferramenta
  de comparação.
- `tools/compare_monthly_values/comparison.py`: modelos e cálculos determinísticos
  de comparação entre meses, sem dependência do LangChain.
- `repository/postgres_financial_data.py`: executa consultas somente leitura no
  PostgreSQL para as ferramentas.
- `prompt_version/`: mantém o prompt atual e seu histórico versionado.
- `tests/`: contém testes unitários, smoke tests e execução manual.

`FinancialDataAgent()` usa PostgreSQL por padrão. Testes podem injetar um reader
alternativo com `FinancialDataAgent(fake_reader)`.

Para executar diretamente em testes ou benchmarks:

```python
component = FinancialDataAgent()
agent = component.as_agent()
result = agent.invoke({"messages": [{"role": "user", "content": question}]})
```

Para disponibilizar o mesmo agente ao AI Manager:

```python
manager = create_ai_manager_agent()
```

O AI Manager registra `FinancialDataAgent().as_tool()` por padrão. Uma tool
explicitamente injetada com o nome `financial_data_agent` substitui a composição
padrão, permitindo o uso de doubles em testes.

## Princípio de confiabilidade

Consultas e cálculos financeiros devem permanecer fora do raciocínio livre do
modelo sempre que puderem ser implementados de forma determinística. Isso torna
os resultados reproduzíveis, testáveis e comparáveis diretamente com o banco de
dados.
