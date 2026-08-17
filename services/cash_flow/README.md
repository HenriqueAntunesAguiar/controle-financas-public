# Cash Flow

Contexto de persistência para lançamentos que não pertencem à fonte imutável
das faturas e para o planejamento mensal.

## Estrutura

- `cash_flow.lancamentos_manuais`: gastos reais ou previstos, com meio de
  pagamento e remoção lógica;
- `cash_flow.recorrencias_lancamento_manual`: recorrências sem prazo ou com mês
  final, preservando configurações encerradas;
- `cash_flow.gastos_previstos_cartao`: tabela de compatibilidade para previsões
  criadas pelo contrato antigo da API;
- `cash_flow.resumos_mensais`: rendimento, valor guardado e resultado aplicado.

As regras de aplicação ficam em `services/invoice_web/fastapi_app/application/`
e o adaptador PostgreSQL fica em
`services/invoice_web/fastapi_app/adapters/outbound/persistence/`.

## Regras principais

- valores de lançamentos devem ser positivos;
- `mes_referencia` sempre representa o primeiro dia do mês;
- remoções são lógicas e preservam o histórico;
- somente uma recorrência pode estar ativa para cada lançamento;
- reaplicar um resultado mensal substitui a aplicação anterior;
- gastos previstos permanecem separados dos compromissos confirmados.

## Migração

`repository/postgres_schema.sql` é idempotente e é aplicado por
`db_schema_setup` depois dos schemas `financeiro` e `spend_label`:

```powershell
docker compose up db_schema_setup
```
