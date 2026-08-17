"""Consultas do contexto spend_label no PostgreSQL local."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi_app.infrastructure.config import PostgresSettings


LATEST_VERSIONS_CTE = """
WITH latest_versions AS (
    SELECT DISTINCT ON (documento_id) id
    FROM financeiro.versoes_fatura
    ORDER BY documento_id, numero_versao DESC
)
"""


class PostgresCategorizationRepository:
    def __init__(self, settings: PostgresSettings):
        self.settings = settings

    def _connect(self):
        import psycopg

        return psycopg.connect(
            host=self.settings.host,
            port=self.settings.port,
            dbname=self.settings.database,
            user=self.settings.user,
            password=self.settings.password,
            connect_timeout=self.settings.connect_timeout,
        )

    @staticmethod
    def _dicts(cursor) -> list[dict[str, Any]]:
        columns = [column.name for column in cursor.description]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def list_categories(self) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.slug, c.nome, parent.slug AS parent_slug
                FROM spend_label.categorias AS c
                LEFT JOIN spend_label.categorias AS parent
                    ON parent.id = c.categoria_pai_id
                WHERE c.ativa
                ORDER BY c.nome
                """
            )
            return self._dicts(cursor)

    def create_category(self, slug: str, name: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO spend_label.categorias (slug, nome)
                VALUES (%s, %s)
                ON CONFLICT (slug) DO UPDATE
                SET ativa = TRUE
                RETURNING slug, nome, NULL::VARCHAR AS parent_slug
                """,
                (slug, name),
            )
            row = cursor.fetchone()
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row, strict=True))

    def list_transactions(self, limit: int, offset: int, query: str, category_slug: str, review_status: str, sort_field: str, sort_direction: str) -> dict[str, Any]:
        sort_columns = {
            "date": "t.data_transacao",
            "merchant": "t.estabelecimento_nome",
            "amount": "t.valor",
            "category": "t.categoria_efetiva",
            "source": "t.categoria_origem",
        }
        order_column = sort_columns.get(sort_field, sort_columns["date"])
        order_direction = "ASC" if sort_direction == "asc" else "DESC"
        text_pattern = f"%{query}%"
        filters = """
            WHERE (
                %s = ''
                OR t.descricao ILIKE %s
                OR t.estabelecimento_nome ILIKE %s
                OR COALESCE(t.localidade, '') ILIKE %s
            )
              AND (%s = '' OR t.categoria_efetiva = %s)
              AND (
                  %s = 'all'
                  OR (%s = 'pending' AND t.categoria_origem = 'parser')
                  OR (%s = 'confirmed' AND t.categoria_origem <> 'parser')
                  OR (%s = 'suggested' AND t.categoria_sugerida IS NOT NULL)
              )
        """
        filter_params = (
            query,
            text_pattern,
            text_pattern,
            text_pattern,
            category_slug,
            category_slug,
            review_status,
            review_status,
            review_status,
            review_status,
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                LATEST_VERSIONS_CTE
                + """
                SELECT COUNT(*)
                FROM spend_label.transacoes_categorizadas AS t
                JOIN latest_versions AS lv ON lv.id = t.versao_id
                """
                + filters,
                filter_params,
            )
            total = int(cursor.fetchone()[0])
            cursor.execute(
                LATEST_VERSIONS_CTE
                + """
                SELECT
                    t.id,
                    t.data_transacao,
                    t.valor,
                    t.descricao,
                    t.descricao_normalizada,
                    t.localidade,
                    t.estabelecimento_id AS alias_hash,
                    COALESCE(
                        t.estabelecimento_canonico_id,
                        t.estabelecimento_id
                    ) AS estabelecimento_id,
                    t.estabelecimento_nome,
                    t.categoria_efetiva,
                    t.categoria_origem,
                    t.categoria_sugerida,
                    t.sugestao_confianca,
                    t.sugestao_modelo_versao,
                    t.parcela_atual,
                    t.total_parcelas,
                    recurrence.modo AS recurrence_mode,
                    recurrence.fim_mes AS recurrence_end_month
                FROM spend_label.transacoes_categorizadas AS t
                JOIN latest_versions AS lv ON lv.id = t.versao_id
                LEFT JOIN spend_label.recorrencias_transacao AS recurrence
                    ON recurrence.transacao_id = t.id AND recurrence.ativa
                """
                + filters
                + f"""
                ORDER BY {order_column} {order_direction} NULLS LAST, t.id DESC
                LIMIT %s OFFSET %s
                """,
                (*filter_params, limit, offset),
            )
            rows = self._dicts(cursor)
        for row in rows:
            row["data_transacao"] = (
                row["data_transacao"].isoformat() if row["data_transacao"] else None
            )
            row["valor"] = format(row["valor"], ".2f")
            if row["sugestao_confianca"] is not None:
                row["sugestao_confianca"] = float(row["sugestao_confianca"])
            if row["recurrence_end_month"] is not None:
                row["recurrence_end_month"] = row[
                    "recurrence_end_month"
                ].strftime("%Y-%m")
        return {"items": rows, "total": total, "limit": limit, "offset": offset}

    def list_merchants(self, query: str, limit: int) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    e.id,
                    e.nome_canonico,
                    c.slug AS categoria_padrao,
                    e.categoria_padrao_confirmada,
                    COUNT(a.alias_hash) AS aliases
                FROM spend_label.estabelecimentos AS e
                LEFT JOIN spend_label.categorias AS c
                    ON c.id = e.categoria_padrao_id
                LEFT JOIN spend_label.aliases_estabelecimento AS a
                    ON a.estabelecimento_id = e.id
                WHERE %s = '' OR e.nome_canonico ILIKE %s
                GROUP BY e.id, c.slug
                ORDER BY e.nome_canonico
                LIMIT %s
                """,
                (query, pattern, limit),
            )
            return self._dicts(cursor)

    def categorize(self, transaction_id: int, category_slug: str, scope: str, merchant_name: str | None) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.id, a.estabelecimento_id
                FROM financeiro.transacoes_versao AS t
                LEFT JOIN spend_label.aliases_estabelecimento AS a
                    ON a.alias_hash = t.estabelecimento_id
                WHERE t.id = %s
                FOR UPDATE OF t
                """,
                (transaction_id,),
            )
            target = cursor.fetchone()
            cursor.execute(
                "SELECT id FROM spend_label.categorias WHERE slug = %s AND ativa",
                (category_slug,),
            )
            category = cursor.fetchone()
            if target is None or category is None or target[1] is None:
                return False
            merchant_id = target[1]
            if scope == "merchant":
                cursor.execute(
                    """
                    UPDATE spend_label.estabelecimentos
                    SET categoria_padrao_id = %s,
                        categoria_padrao_confirmada = TRUE,
                        nome_canonico = COALESCE(%s, nome_canonico),
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (category[0], merchant_name, merchant_id),
                )
                cursor.execute(
                    """
                    UPDATE spend_label.aliases_estabelecimento
                    SET confirmado = TRUE,
                        origem = 'manual',
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE estabelecimento_id = %s
                    """,
                    (merchant_id,),
                )
            else:
                cursor.execute(
                    """
                    UPDATE spend_label.classificacoes_transacao
                    SET ativa = FALSE
                    WHERE transacao_id = %s AND ativa
                    """,
                    (transaction_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO spend_label.classificacoes_transacao(
                        transacao_id, categoria_id, origem, confirmada,
                        ativa, confirmada_em
                    ) VALUES (%s, %s, 'manual', TRUE, TRUE, CURRENT_TIMESTAMP)
                    """,
                    (transaction_id, category[0]),
                )
                if merchant_name is not None:
                    cursor.execute(
                        """
                        UPDATE spend_label.estabelecimentos
                        SET nome_canonico = %s, atualizado_em = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (merchant_name, merchant_id),
                    )
        return True

    def merge_alias(self, alias_hash: str, merchant_id: str) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM spend_label.estabelecimentos WHERE id = %s",
                (merchant_id,),
            )
            if cursor.fetchone() is None:
                return False
            cursor.execute(
                """
                UPDATE spend_label.aliases_estabelecimento
                SET estabelecimento_id = %s,
                    origem = 'manual',
                    confirmado = TRUE,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE alias_hash = %s
                """,
                (merchant_id, alias_hash),
            )
            return cursor.rowcount == 1

    def set_recurrence(self, transaction_id: int, mode: str, end_month: str | None) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM financeiro.transacoes_versao WHERE id = %s FOR UPDATE",
                (transaction_id,),
            )
            if cursor.fetchone() is None:
                return False
            cursor.execute(
                """
                UPDATE spend_label.recorrencias_transacao
                SET ativa = FALSE, encerrada_em = CURRENT_TIMESTAMP
                WHERE transacao_id = %s AND ativa
                """,
                (transaction_id,),
            )
            if mode != "none":
                cursor.execute(
                    """
                    INSERT INTO spend_label.recorrencias_transacao(
                        transacao_id, modo, fim_mes
                    ) VALUES (%s, %s, %s::text::date)
                    """,
                    (
                        transaction_id,
                        mode,
                        f"{end_month}-01" if end_month is not None else None,
                    ),
                )
        return True

    def monthly_totals(self, months: int, include_card: bool, include_manual: bool, include_actual: bool, include_projected: bool, include_expense_income: bool) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    v.id,
                    DATE_TRUNC('month', v.data_referencia)::date AS reference_month
                FROM financeiro.versoes_fatura AS v
                ORDER BY v.data_referencia DESC, v.importado_em DESC, v.id DESC
                LIMIT 1
                """
            )
            latest = cursor.fetchone()
            if latest is None:
                return {"reference_month": None, "series": []}

            version_id, reference_month = latest
            cursor.execute(
                """
                WITH base_transactions AS (
                    SELECT
                        t.id,
                        t.valor,
                        t.tipo,
                        t.categoria_efetiva AS category,
                        t.parcela_atual,
                        t.total_parcelas,
                        recurrence.id AS recurrence_id
                    FROM spend_label.transacoes_categorizadas AS t
                    LEFT JOIN spend_label.recorrencias_transacao AS recurrence
                        ON recurrence.transacao_id = t.id AND recurrence.ativa
                    WHERE t.versao_id = %(version_id)s
                ), recurring_transactions AS (
                    SELECT
                        t.valor,
                        t.tipo,
                        t.categoria_efetiva AS category,
                        recurrence.modo,
                        recurrence.fim_mes
                    FROM spend_label.recorrencias_transacao AS recurrence
                    JOIN spend_label.transacoes_categorizadas AS t
                        ON t.id = recurrence.transacao_id
                    WHERE recurrence.ativa
                ), recurring_manual_expenses AS (
                    SELECT
                        manual.mes_referencia AS start_month,
                        manual.valor,
                        category.slug AS category,
                        manual.meio_pagamento,
                        manual.tipo_lancamento,
                        recurrence.modo,
                        recurrence.fim_mes
                    FROM cash_flow.recorrencias_lancamento_manual AS recurrence
                    JOIN cash_flow.lancamentos_manuais AS manual
                        ON manual.id = recurrence.lancamento_id
                    JOIN spend_label.categorias AS category
                        ON category.id = manual.categoria_id
                    WHERE recurrence.ativa AND manual.ativo
                ), occurrences AS (
                    SELECT
                        %(reference_month)s::date AS occurrence_month,
                        b.category,
                        b.valor,
                        'actual'::text AS kind
                    FROM base_transactions AS b
                    WHERE %(include_card)s
                      AND %(include_actual)s

                    UNION ALL

                    SELECT
                        (%(reference_month)s::date
                            + MAKE_INTERVAL(months => installment.number))::date,
                        b.category,
                        b.valor,
                        'actual'::text AS kind
                    FROM base_transactions AS b
                    CROSS JOIN LATERAL GENERATE_SERIES(
                        1,
                        LEAST(
                            GREATEST(b.total_parcelas - b.parcela_atual, 0),
                            %(months)s - 1
                        )
                    ) AS installment(number)
                    WHERE b.tipo = 'compra'
                      AND %(include_card)s
                      AND %(include_actual)s
                      AND b.valor > 0
                      AND b.parcela_atual IS NOT NULL
                      AND b.total_parcelas IS NOT NULL
                      AND b.parcela_atual < b.total_parcelas
                      AND b.recurrence_id IS NULL

                    UNION ALL

                    SELECT
                        (%(reference_month)s::date
                            + MAKE_INTERVAL(months => recurrence.number))::date,
                        recurring.category,
                        recurring.valor,
                        'actual'::text AS kind
                    FROM recurring_transactions AS recurring
                    CROSS JOIN LATERAL GENERATE_SERIES(1, %(months)s - 1)
                        AS recurrence(number)
                    WHERE recurring.tipo = 'compra'
                      AND %(include_card)s
                      AND %(include_actual)s
                      AND recurring.valor > 0
                      AND (
                          recurring.modo = 'unlimited'
                          OR (%(reference_month)s::date
                              + MAKE_INTERVAL(months => recurrence.number))::date
                              <= recurring.fim_mes
                      )

                    UNION ALL

                    SELECT
                        manual.mes_referencia,
                        category.slug,
                        manual.valor,
                        CASE manual.tipo_lancamento
                            WHEN 'actual' THEN 'actual'::text
                            ELSE 'projected'::text
                        END AS kind
                    FROM cash_flow.lancamentos_manuais AS manual
                    JOIN spend_label.categorias AS category
                        ON category.id = manual.categoria_id
                    WHERE manual.ativo
                      AND (
                          (manual.meio_pagamento = 'credito' AND %(include_card)s)
                          OR (
                              manual.meio_pagamento <> 'credito'
                              AND %(include_manual)s
                          )
                      )
                      AND (
                          (manual.tipo_lancamento = 'actual' AND %(include_actual)s)
                          OR (
                              manual.tipo_lancamento = 'planned'
                              AND %(include_projected)s
                          )
                      )
                      AND manual.mes_referencia >= %(reference_month)s::date
                      AND manual.mes_referencia
                          < %(reference_month)s::date
                              + MAKE_INTERVAL(months => %(months)s)

                    UNION ALL

                    SELECT
                        occurrence.month::date,
                        recurring.category,
                        recurring.valor,
                        CASE recurring.tipo_lancamento
                            WHEN 'actual' THEN 'actual'::text
                            ELSE 'projected'::text
                        END AS kind
                    FROM recurring_manual_expenses AS recurring
                    CROSS JOIN LATERAL GENERATE_SERIES(
                        recurring.start_month + INTERVAL '1 month',
                        %(reference_month)s::date
                            + MAKE_INTERVAL(months => %(months)s - 1),
                        INTERVAL '1 month'
                    ) AS occurrence(month)
                    WHERE (
                          (recurring.meio_pagamento = 'credito' AND %(include_card)s)
                          OR (
                              recurring.meio_pagamento <> 'credito'
                              AND %(include_manual)s
                          )
                      )
                      AND (
                          (
                              recurring.tipo_lancamento = 'actual'
                              AND %(include_actual)s
                          )
                          OR (
                              recurring.tipo_lancamento = 'planned'
                              AND %(include_projected)s
                          )
                      )
                      AND occurrence.month >= %(reference_month)s::date
                      AND (
                          recurring.modo = 'unlimited'
                          OR occurrence.month <= recurring.fim_mes
                      )
                )
                SELECT
                    TO_CHAR(occurrence_month, 'YYYY-MM') AS month,
                    category,
                    kind,
                    SUM(valor) AS total
                FROM occurrences
                GROUP BY occurrence_month, category, kind
                ORDER BY occurrence_month, category, kind
                """,
                {
                    "version_id": version_id,
                    "reference_month": reference_month,
                    "months": months,
                    "include_card": include_card,
                    "include_manual": include_manual,
                    "include_actual": include_actual,
                    "include_projected": include_projected,
                },
            )
            series = self._dicts(cursor)
            monthly_income = []
            saved_base = Decimal("0")
            if include_expense_income:
                cursor.execute(
                    """
                    SELECT COALESCE((
                        SELECT guardado_base
                        FROM cash_flow.resumos_mensais
                        WHERE mes_referencia = %s::date
                    ), 0)
                    """,
                    (reference_month,),
                )
                saved_base = cursor.fetchone()[0]
                cursor.execute(
                    """
                    SELECT
                        TO_CHAR(months.month, 'YYYY-MM') AS month,
                        COALESCE(summary.rendimento, 0) AS income
                    FROM GENERATE_SERIES(0, %s - 1) AS offsets(number)
                    CROSS JOIN LATERAL (
                        SELECT (%s::date + MAKE_INTERVAL(months => offsets.number))::date
                            AS month
                    ) AS months
                    LEFT JOIN LATERAL (
                        SELECT rendimento
                        FROM cash_flow.resumos_mensais
                        WHERE mes_referencia <= months.month
                        ORDER BY mes_referencia DESC
                        LIMIT 1
                    ) AS summary ON TRUE
                    ORDER BY months.month
                    """,
                    (months, reference_month),
                )
                monthly_income = self._dicts(cursor)
            return {
                "reference_month": reference_month.strftime("%Y-%m"),
                "series": series,
                "monthly_income": monthly_income,
                "saved_base": saved_base,
            }

    def monthly_breakdown(self, month: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    v.id,
                    DATE_TRUNC('month', v.data_referencia)::date
                FROM financeiro.versoes_fatura AS v
                ORDER BY v.data_referencia DESC, v.importado_em DESC, v.id DESC
                LIMIT 1
                """
            )
            latest = cursor.fetchone()
            if latest is None:
                return {"reference_month": None, "entries": []}
            version_id, reference_month = latest
            cursor.execute(
                """
                WITH settings AS (
                    SELECT
                        %s::bigint AS version_id,
                        %s::date AS reference_month,
                        %s::date AS target_month
                ), entries AS (
                    SELECT
                        CONCAT('invoice-', transaction.id) AS entry_id,
                        transaction.categoria_efetiva AS category,
                        COALESCE(
                            NULLIF(transaction.estabelecimento_nome, ''),
                            transaction.descricao
                        ) AS description,
                        transaction.valor AS amount,
                        CASE
                            WHEN transaction.parcela_atual IS NOT NULL
                                AND transaction.total_parcelas IS NOT NULL
                            THEN CONCAT(
                                'Fatura · parcela ', transaction.parcela_atual,
                                '/', transaction.total_parcelas
                            )
                            ELSE 'Fatura'
                        END AS source_label,
                        'card'::text AS source_group,
                        'actual'::text AS kind
                    FROM spend_label.transacoes_categorizadas AS transaction
                    CROSS JOIN settings
                    WHERE transaction.versao_id = settings.version_id
                      AND settings.target_month = settings.reference_month

                    UNION ALL

                    SELECT
                        CONCAT('installment-', transaction.id, '-', installment.number),
                        transaction.categoria_efetiva,
                        COALESCE(
                            NULLIF(transaction.estabelecimento_nome, ''),
                            transaction.descricao
                        ),
                        transaction.valor,
                        CONCAT(
                            'Cartão · parcela ',
                            transaction.parcela_atual + installment.number,
                            '/', transaction.total_parcelas
                        ),
                        'card'::text,
                        'actual'::text
                    FROM spend_label.transacoes_categorizadas AS transaction
                    CROSS JOIN settings
                    CROSS JOIN LATERAL GENERATE_SERIES(
                        1,
                        GREATEST(
                            transaction.total_parcelas - transaction.parcela_atual,
                            0
                        )
                    ) AS installment(number)
                    LEFT JOIN spend_label.recorrencias_transacao AS recurrence
                        ON recurrence.transacao_id = transaction.id AND recurrence.ativa
                    WHERE transaction.versao_id = settings.version_id
                      AND transaction.tipo = 'compra'
                      AND transaction.valor > 0
                      AND transaction.parcela_atual IS NOT NULL
                      AND transaction.total_parcelas IS NOT NULL
                      AND transaction.parcela_atual < transaction.total_parcelas
                      AND recurrence.id IS NULL
                      AND settings.target_month = settings.reference_month
                          + MAKE_INTERVAL(months => installment.number)

                    UNION ALL

                    SELECT
                        CONCAT('recurring-card-', transaction.id, '-', settings.target_month),
                        transaction.categoria_efetiva,
                        COALESCE(
                            NULLIF(transaction.estabelecimento_nome, ''),
                            transaction.descricao
                        ),
                        transaction.valor,
                        'Cartão · recorrente',
                        'card'::text,
                        'actual'::text
                    FROM spend_label.recorrencias_transacao AS recurrence
                    JOIN spend_label.transacoes_categorizadas AS transaction
                        ON transaction.id = recurrence.transacao_id
                    CROSS JOIN settings
                    WHERE recurrence.ativa
                      AND transaction.tipo = 'compra'
                      AND transaction.valor > 0
                      AND settings.target_month > settings.reference_month
                      AND (
                          recurrence.modo = 'unlimited'
                          OR settings.target_month <= recurrence.fim_mes
                      )

                    UNION ALL

                    SELECT
                        CONCAT('manual-', manual.id),
                        category.slug,
                        manual.descricao,
                        manual.valor,
                        CONCAT(
                            CASE
                                WHEN manual.meio_pagamento = 'credito'
                                THEN 'Cartão'
                                ELSE 'Outro'
                            END,
                            ' · ', manual.meio_pagamento,
                            CASE manual.tipo_lancamento
                                WHEN 'planned' THEN ' · previsto'
                                ELSE ' · real'
                            END
                        ),
                        CASE
                            WHEN manual.meio_pagamento = 'credito'
                            THEN 'card'::text
                            ELSE 'manual'::text
                        END,
                        CASE manual.tipo_lancamento
                            WHEN 'actual' THEN 'actual'::text
                            ELSE 'projected'::text
                        END
                    FROM cash_flow.lancamentos_manuais AS manual
                    JOIN spend_label.categorias AS category
                        ON category.id = manual.categoria_id
                    CROSS JOIN settings
                    WHERE manual.ativo
                      AND manual.mes_referencia = settings.target_month
                      AND manual.mes_referencia >= settings.reference_month

                    UNION ALL

                    SELECT
                        CONCAT('recurring-manual-', manual.id, '-', settings.target_month),
                        category.slug,
                        manual.descricao,
                        manual.valor,
                        CONCAT(
                            CASE
                                WHEN manual.meio_pagamento = 'credito'
                                THEN 'Cartão recorrente'
                                ELSE 'Outro recorrente'
                            END,
                            ' · ', manual.meio_pagamento
                        ),
                        CASE
                            WHEN manual.meio_pagamento = 'credito'
                            THEN 'card'::text
                            ELSE 'manual'::text
                        END,
                        CASE manual.tipo_lancamento
                            WHEN 'actual' THEN 'actual'::text
                            ELSE 'projected'::text
                        END
                    FROM cash_flow.recorrencias_lancamento_manual AS recurrence
                    JOIN cash_flow.lancamentos_manuais AS manual
                        ON manual.id = recurrence.lancamento_id
                    JOIN spend_label.categorias AS category
                        ON category.id = manual.categoria_id
                    CROSS JOIN settings
                    WHERE recurrence.ativa
                      AND manual.ativo
                      AND settings.target_month > manual.mes_referencia
                      AND settings.target_month >= settings.reference_month
                      AND (
                          recurrence.modo = 'unlimited'
                          OR settings.target_month <= recurrence.fim_mes
                      )
                )
                SELECT
                    entries.entry_id,
                    entries.category,
                    COALESCE(
                        category.nome,
                        INITCAP(REPLACE(entries.category, '_', ' '))
                    ) AS category_name,
                    entries.description,
                    entries.amount,
                    entries.source_label,
                    entries.source_group,
                    entries.kind
                FROM entries
                LEFT JOIN spend_label.categorias AS category
                    ON category.slug = entries.category
                ORDER BY category_name, entries.amount DESC, entries.entry_id
                """,
                (version_id, reference_month, f"{month}-01"),
            )
            return {
                "reference_month": reference_month.strftime("%Y-%m"),
                "entries": self._dicts(cursor),
            }
