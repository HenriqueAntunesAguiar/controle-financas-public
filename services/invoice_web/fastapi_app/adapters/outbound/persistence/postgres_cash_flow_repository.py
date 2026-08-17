"""Persistência PostgreSQL do contexto de fluxo de caixa."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi_app.infrastructure.config import PostgresSettings


class PostgresCashFlowRepository:
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
    def _row(cursor) -> dict[str, Any]:
        columns = [column.name for column in cursor.description]
        return dict(zip(columns, cursor.fetchone(), strict=True))

    def latest_invoice_month(self) -> str | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT TO_CHAR(DATE_TRUNC('month', data_referencia), 'YYYY-MM')
                FROM financeiro.versoes_fatura
                ORDER BY data_referencia DESC, importado_em DESC, id DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            return row[0] if row is not None else None

    def create_card_forecast(self, month: str, description: str, amount: Decimal, category_slug: str) -> dict[str, Any] | None:
        result = self.create_expense(
            month,
            description,
            amount,
            category_slug,
            "credito",
            "planned",
            "none",
            None,
        )
        if result is not None:
            result["covered_by_invoice"] = False
        return result

    def list_card_forecasts(self, month: str | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT expense.id,
                       TO_CHAR(expense.mes_referencia, 'YYYY-MM') AS month,
                       expense.descricao AS description,
                       expense.valor AS amount,
                       category.slug AS category_slug,
                       category.nome AS category_name,
                       EXISTS (
                           SELECT 1 FROM financeiro.versoes_fatura AS version
                           WHERE DATE_TRUNC('month', version.data_referencia)::date
                               = expense.mes_referencia
                       ) AS covered_by_invoice
                FROM cash_flow.lancamentos_manuais AS expense
                JOIN spend_label.categorias AS category
                    ON category.id = expense.categoria_id
                WHERE expense.ativo
                  AND expense.meio_pagamento = 'credito'
                  AND expense.tipo_lancamento = 'planned'
                  AND (%s::text IS NULL OR expense.mes_referencia = %s::date)
                ORDER BY expense.mes_referencia, expense.id DESC
                LIMIT %s
                """,
                (month, f"{month}-01" if month else None, limit),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def remove_card_forecast(self, forecast_id: int) -> bool:
        return self.remove_expense(forecast_id)

    def create_expense(self, month: str, description: str, amount: Decimal, category_slug: str, payment_method: str, expense_type: str, recurrence_mode: str, recurrence_end_month: str | None) -> dict[str, Any] | None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, nome FROM spend_label.categorias WHERE slug = %s AND ativa",
                (category_slug,),
            )
            category = cursor.fetchone()
            if category is None:
                return None
            cursor.execute(
                """
                INSERT INTO cash_flow.lancamentos_manuais(
                    mes_referencia, descricao, valor, categoria_id,
                    meio_pagamento, tipo_lancamento
                ) VALUES (%s::date, %s, %s, %s, %s, %s)
                RETURNING id, TO_CHAR(mes_referencia, 'YYYY-MM') AS month,
                          descricao AS description, valor AS amount,
                          meio_pagamento AS payment_method,
                          tipo_lancamento AS expense_type
                """,
                (
                    f"{month}-01", description, amount, category[0],
                    payment_method, expense_type,
                ),
            )
            result = self._row(cursor)
            if recurrence_mode != "none":
                cursor.execute(
                    """
                    INSERT INTO cash_flow.recorrencias_lancamento_manual(
                        lancamento_id, modo, fim_mes
                    ) VALUES (%s, %s, %s::text::date)
                    """,
                    (
                        result["id"],
                        recurrence_mode,
                        f"{recurrence_end_month}-01"
                        if recurrence_end_month is not None else None,
                    ),
                )
            result.update(category_slug=category_slug, category_name=category[1])
            result.update(
                recurrence_mode=(
                    recurrence_mode if recurrence_mode != "none" else None
                ),
                recurrence_end_month=recurrence_end_month,
            )
            return result

    def list_expenses(self, month: str | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT expense.id,
                       TO_CHAR(expense.mes_referencia, 'YYYY-MM') AS month,
                       expense.descricao AS description,
                       expense.valor AS amount,
                       category.slug AS category_slug,
                       category.nome AS category_name,
                       expense.meio_pagamento AS payment_method,
                       expense.tipo_lancamento AS expense_type,
                       recurrence.modo AS recurrence_mode,
                       TO_CHAR(recurrence.fim_mes, 'YYYY-MM') AS recurrence_end_month,
                       EXISTS (
                           SELECT 1 FROM financeiro.versoes_fatura AS version
                           WHERE DATE_TRUNC('month', version.data_referencia)::date
                               = expense.mes_referencia
                       ) AS covered_by_invoice
                FROM cash_flow.lancamentos_manuais AS expense
                JOIN spend_label.categorias AS category ON category.id = expense.categoria_id
                LEFT JOIN cash_flow.recorrencias_lancamento_manual AS recurrence
                    ON recurrence.lancamento_id = expense.id AND recurrence.ativa
                WHERE expense.ativo
                  AND (%s::text IS NULL OR expense.mes_referencia = %s::date)
                ORDER BY expense.mes_referencia DESC, expense.id DESC
                LIMIT %s
                """,
                (month, f"{month}-01" if month else None, limit),
            )
            columns = [column.name for column in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def update_expense(self, expense_id: int, month: str, description: str, amount: Decimal, category_slug: str, payment_method: str, expense_type: str, recurrence_mode: str, recurrence_end_month: str | None) -> dict[str, Any] | str:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, nome FROM spend_label.categorias WHERE slug = %s AND ativa",
                (category_slug,),
            )
            category = cursor.fetchone()
            if category is None:
                return "category_not_found"
            cursor.execute(
                """
                SELECT id
                FROM cash_flow.lancamentos_manuais
                WHERE id = %s AND ativo
                FOR UPDATE
                """,
                (expense_id,),
            )
            if cursor.fetchone() is None:
                return "not_found"
            cursor.execute(
                """
                UPDATE cash_flow.lancamentos_manuais
                SET mes_referencia = %s::date,
                    descricao = %s,
                    valor = %s,
                    categoria_id = %s,
                    meio_pagamento = %s,
                    tipo_lancamento = %s
                WHERE id = %s
                RETURNING id, TO_CHAR(mes_referencia, 'YYYY-MM') AS month,
                          descricao AS description, valor AS amount,
                          meio_pagamento AS payment_method,
                          tipo_lancamento AS expense_type
                """,
                (
                    f"{month}-01", description, amount, category[0],
                    payment_method, expense_type, expense_id,
                ),
            )
            result = self._row(cursor)
            cursor.execute(
                """
                UPDATE cash_flow.recorrencias_lancamento_manual
                SET ativa = FALSE, encerrada_em = CURRENT_TIMESTAMP
                WHERE lancamento_id = %s AND ativa
                """,
                (expense_id,),
            )
            if recurrence_mode != "none":
                cursor.execute(
                    """
                    INSERT INTO cash_flow.recorrencias_lancamento_manual(
                        lancamento_id, modo, fim_mes
                    ) VALUES (%s, %s, %s::text::date)
                    """,
                    (
                        expense_id,
                        recurrence_mode,
                        f"{recurrence_end_month}-01"
                        if recurrence_end_month is not None else None,
                    ),
                )
            result.update(category_slug=category_slug, category_name=category[1])
            result.update(
                recurrence_mode=(
                    recurrence_mode if recurrence_mode != "none" else None
                ),
                recurrence_end_month=recurrence_end_month,
            )
            return result

    def remove_expense(self, expense_id: int) -> bool:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE cash_flow.recorrencias_lancamento_manual
                SET ativa = FALSE, encerrada_em = CURRENT_TIMESTAMP
                WHERE lancamento_id = %s AND ativa
                """,
                (expense_id,),
            )
            cursor.execute(
                """
                UPDATE cash_flow.lancamentos_manuais
                SET ativo = FALSE, removido_em = CURRENT_TIMESTAMP
                WHERE id = %s AND ativo
                """,
                (expense_id,),
            )
            return cursor.rowcount == 1

    def set_expense_recurrence(self, expense_id: int, mode: str, end_month: str | None) -> str:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT mes_referencia
                FROM cash_flow.lancamentos_manuais
                WHERE id = %s AND ativo
                FOR UPDATE
                """,
                (expense_id,),
            )
            expense = cursor.fetchone()
            if expense is None:
                return "not_found"
            end_date = f"{end_month}-01" if end_month is not None else None
            if end_date is not None and end_date < expense[0].isoformat():
                return "invalid_end"
            cursor.execute(
                """
                UPDATE cash_flow.recorrencias_lancamento_manual
                SET ativa = FALSE, encerrada_em = CURRENT_TIMESTAMP
                WHERE lancamento_id = %s AND ativa
                """,
                (expense_id,),
            )
            if mode != "none":
                cursor.execute(
                    """
                    INSERT INTO cash_flow.recorrencias_lancamento_manual(
                        lancamento_id, modo, fim_mes
                    ) VALUES (%s, %s, %s::text::date)
                    """,
                    (expense_id, mode, end_date),
                )
            return "updated"

    @staticmethod
    def _expense_totals(cursor, month: str) -> tuple[Decimal, Decimal]:
        month_date = f"{month}-01"
        cursor.execute(
            """
            WITH target_version AS (
                SELECT id FROM financeiro.versoes_fatura
                WHERE DATE_TRUNC('month', data_referencia)::date = %s::date
                ORDER BY importado_em DESC, id DESC LIMIT 1
            ), actual_total AS (
                SELECT COALESCE(SUM(transaction.valor), 0) AS total
                FROM financeiro.transacoes_versao AS transaction
                JOIN target_version ON target_version.id = transaction.versao_id
            ), expense_occurrences AS (
                SELECT expense.valor, expense.meio_pagamento
                FROM cash_flow.lancamentos_manuais AS expense
                WHERE expense.ativo
                  AND (
                      expense.mes_referencia = %s::date
                      OR (
                          expense.mes_referencia < %s::date
                          AND EXISTS (
                              SELECT 1
                              FROM cash_flow.recorrencias_lancamento_manual AS recurrence
                              WHERE recurrence.lancamento_id = expense.id
                                AND recurrence.ativa
                                AND (
                                    recurrence.modo = 'unlimited'
                                    OR %s::date <= recurrence.fim_mes
                                )
                          )
                      )
                  )
                  AND expense.tipo_lancamento = 'actual'
                  AND (
                      expense.meio_pagamento <> 'credito'
                      OR NOT EXISTS (SELECT 1 FROM target_version)
                  )
            )
            SELECT
                actual_total.total + COALESCE(SUM(expense.valor) FILTER (
                    WHERE expense.meio_pagamento = 'credito'
                ), 0) AS card,
                COALESCE(SUM(expense.valor) FILTER (
                    WHERE expense.meio_pagamento <> 'credito'
                ), 0) AS manual
            FROM actual_total
            LEFT JOIN expense_occurrences AS expense ON TRUE
            GROUP BY actual_total.total
            """,
            (month_date, month_date, month_date, month_date),
        )
        return cursor.fetchone()

    @classmethod
    def _summary(cls, cursor, month: str, include_manual: bool = True) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT rendimento, guardado_base, resultado_aplicado
            FROM cash_flow.resumos_mensais WHERE mes_referencia = %s::date
            """,
            (f"{month}-01",),
        )
        stored = cursor.fetchone() or (Decimal("0"), Decimal("0"), None)
        card, manual = cls._expense_totals(cursor, month)
        expenses = card + (manual if include_manual else Decimal("0"))
        result = stored[0] - expenses
        applied = stored[2]
        return {
            "month": month, "income": stored[0], "saved_base": stored[1],
            "card_expenses": card, "manual_expenses": manual,
            "total_expenses": expenses, "result": result,
            "include_manual": include_manual,
            "applied_result": applied,
            "saved_total": stored[1] + (applied or Decimal("0")),
        }

    def get_monthly_summary(self, month: str, include_manual: bool = True) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            return self._summary(cursor, month, include_manual)

    def save_monthly_summary(self, month: str, income: Decimal, saved_base: Decimal) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO cash_flow.resumos_mensais(
                    mes_referencia, rendimento, guardado_base
                ) VALUES (%s::date, %s, %s)
                ON CONFLICT (mes_referencia) DO UPDATE
                SET rendimento = EXCLUDED.rendimento,
                    guardado_base = EXCLUDED.guardado_base,
                    atualizado_em = CURRENT_TIMESTAMP
                """,
                (f"{month}-01", income, saved_base),
            )
            return self._summary(cursor, month)

    def apply_monthly_result(self, month: str) -> dict[str, Any]:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO cash_flow.resumos_mensais(mes_referencia)
                VALUES (%s::date) ON CONFLICT (mes_referencia) DO NOTHING
                """,
                (f"{month}-01",),
            )
            cursor.execute(
                """
                SELECT 1 FROM cash_flow.resumos_mensais
                WHERE mes_referencia = %s::date FOR UPDATE
                """,
                (f"{month}-01",),
            )
            summary = self._summary(cursor, month)
            cursor.execute(
                """
                UPDATE cash_flow.resumos_mensais
                SET resultado_aplicado = %s, atualizado_em = CURRENT_TIMESTAMP
                WHERE mes_referencia = %s::date
                """,
                (summary["result"], f"{month}-01"),
            )
            return self._summary(cursor, month)
