# Spend Label

Contexto responsável por reconhecer estabelecimentos, categorizar transações
e preservar somente confirmações humanas como exemplos confiáveis.

## Responsabilidades

- `financeiro.transacoes_versao` permanece como fonte imutável da fatura;
- `spend_label.categorias` define a taxonomia ativa;
- `spend_label.estabelecimentos` representa a empresa canônica;
- `spend_label.aliases_estabelecimento` associa descrições equivalentes;
- `spend_label.classificacoes_transacao` guarda sugestões e confirmações;
- `spend_label.recorrencias_transacao` controla projeções recorrentes;
- `spend_label.exemplos_treinamento` expõe somente rótulos confirmados.

A aplicação FastAPI fornece a interface e os endpoints para listar
transações, confirmar categorias, administrar estabelecimentos e unir aliases.
O adaptador correspondente fica em
`services/invoice_web/fastapi_app/adapters/outbound/persistence/`.

## Categoria efetiva

Uma previsão do modelo não se torna verdade automaticamente. A view
`spend_label.transacoes_categorizadas` resolve a categoria nesta ordem:

1. correção confirmada da transação;
2. categoria padrão confirmada do estabelecimento;
3. categoria original produzida pelo parser.

Sugestões não confirmadas ficam em colunas separadas e não entram na view de
exemplos de treinamento.

## Migração

`repository/postgres_schema.sql` é idempotente. Ele cria o schema, as categorias
iniciais, tabelas, índices e views. Quando encontra a tabela legada
`financeiro.rotulos_estabelecimento`, também preserva seus rótulos; instalações
novas não dependem dessa tabela.

O serviço de execução única `db_schema_setup`, definido no Compose da raiz,
aplica esta migração depois de `financeiro` e antes de `cash_flow`. Ele encerra
com código zero e pode ser executado novamente com segurança.

Para reaplicar as migrações:

```powershell
docker compose up db_schema_setup
```
