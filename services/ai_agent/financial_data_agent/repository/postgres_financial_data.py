"""Adaptadores de leitura usados pelas ferramentas financeiras."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from ..tools import DataKind


SOURCES = ("credit_card", "other_transactions")
VALUE_KINDS = (
    "invoice_actual",
    "card_projected",
    "manual_actual",
    "manual_projected",
)


@dataclass(frozen=True)
class PostgresConnectionSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_timeout: int = 10
    statement_timeout_ms: int = 5_000

    @classmethod
    def from_environment(cls) -> "PostgresConnectionSettings":
        return cls(
            host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            database=os.environ.get("POSTGRES_DB", "controle_financas"),
            user=os.environ.get("POSTGRES_USER", "postgres"),
            password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        )


class PostgresFinancialDataReader:
    """Consulta valores realizados e projetados em modo somente leitura."""

    def __init__(self, settings: PostgresConnectionSettings):
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
            application_name="financial_data_agent",
            options=(
                "-c default_transaction_read_only=on "
                f"-c statement_timeout={self.settings.statement_timeout_ms}"
            ),
        )

    @staticmethod
    def _month_start(month: str) -> date:
        try:
            return date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError(
                f"Mes invalido: {month!r}. Use o formato YYYY-MM."
            ) from exc

    def get_monthly_values(self, months: list[str], data_kind: DataKind) -> list[dict[str, Any]]:
        """Retorna meses sem confundir origem, realizado e projecao."""

        requested_months = list(dict.fromkeys(months))
        month_starts = [self._month_start(month) for month in requested_months]

        with self._connect() as connection, connection.cursor() as cursor:
            metadata = self._metadata(cursor, month_starts)
            rows = self._values(cursor, month_starts)

        raw = self._raw_values(requested_months, rows)
        reference_month = next(
            (item["reference_month"] for item in metadata.values()), None
        )
        return [
            self._build_month(
                month=month,
                requested_kind=data_kind,
                metadata=metadata[month],
                raw=raw[month],
                reference_month=reference_month,
            )
            for month in requested_months
        ]

    def get_expense_by_id(self, expense_id: int) -> dict[str, Any] | None:
        """Retorna um lancamento manual ativo pelo identificador."""
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    expense.id,
                    TO_CHAR(expense.mes_referencia, 'YYYY-MM') AS month,
                    expense.descricao AS description,
                    expense.valor AS amount,
                    category.slug AS category_slug,
                    category.nome AS category_name,
                    expense.meio_pagamento AS payment_method,
                    expense.tipo_lancamento AS expense_type,
                    recurrence.modo AS recurrence_mode,
                    TO_CHAR(recurrence.fim_mes, 'YYYY-MM') AS recurrence_end_month
                FROM cash_flow.lancamentos_manuais AS expense
                JOIN spend_label.categorias AS category
                  ON category.id = expense.categoria_id
                LEFT JOIN LATERAL (
                    SELECT active_recurrence.modo, active_recurrence.fim_mes
                    FROM cash_flow.recorrencias_lancamento_manual AS active_recurrence
                    WHERE active_recurrence.lancamento_id = expense.id
                      AND active_recurrence.ativa
                    ORDER BY active_recurrence.id DESC
                    LIMIT 1
                ) AS recurrence ON TRUE
                WHERE expense.id = %s
                  AND expense.ativo
                """,
                (expense_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [column.name for column in cursor.description]
            return dict(zip(columns, row, strict=True))

    @staticmethod
    def _metadata(cursor, month_starts: list[date]) -> dict[str, dict[str, Any]]:
        cursor.execute(
            """
            WITH requested_months AS (
                SELECT UNNEST(%s::date[]) AS month_start
            ), latest_reference AS (
                SELECT MAX(
                    DATE_TRUNC('month', data_referencia)::date
                ) AS month_start
                FROM financeiro.versoes_fatura
            )
            SELECT
                TO_CHAR(requested.month_start, 'YYYY-MM') AS month,
                TO_CHAR(reference.month_start, 'YYYY-MM') AS reference_month,
                TO_CHAR(DATE_TRUNC('month', CURRENT_DATE), 'YYYY-MM')
                    AS current_month,
                EXISTS (
                    SELECT 1
                    FROM financeiro.versoes_fatura AS version
                    WHERE DATE_TRUNC(
                        'month', version.data_referencia
                    )::date = requested.month_start
                ) AS invoice_exists
            FROM requested_months AS requested
            CROSS JOIN latest_reference AS reference
            ORDER BY requested.month_start
            """,
            (month_starts,),
        )
        return {
            month: {
                "reference_month": reference_month,
                "current_month": current_month,
                "invoice_exists": invoice_exists,
            }
            for month, reference_month, current_month, invoice_exists
            in cursor.fetchall()
        }

    @staticmethod
    def _values(cursor, month_starts: list[date]) -> list[tuple]:
        cursor.execute(
            """
            WITH requested_months AS (
                SELECT UNNEST(%s::date[]) AS month_start
            ), latest_reference AS (
                SELECT MAX(
                    DATE_TRUNC('month', data_referencia)::date
                ) AS month_start
                FROM financeiro.versoes_fatura
            ), actual_versions AS (
                SELECT DISTINCT ON (
                    version.documento_id,
                    DATE_TRUNC('month', version.data_referencia)::date
                )
                    version.id,
                    DATE_TRUNC('month', version.data_referencia)::date
                        AS month_start
                FROM financeiro.versoes_fatura AS version
                JOIN requested_months AS requested
                  ON requested.month_start = DATE_TRUNC(
                      'month', version.data_referencia
                  )::date
                ORDER BY
                    version.documento_id,
                    DATE_TRUNC('month', version.data_referencia)::date,
                    version.numero_versao DESC,
                    version.importado_em DESC,
                    version.id DESC
            ), reference_versions AS (
                SELECT DISTINCT ON (version.documento_id)
                    version.id
                FROM financeiro.versoes_fatura AS version
                CROSS JOIN latest_reference AS reference
                WHERE DATE_TRUNC('month', version.data_referencia)::date
                    = reference.month_start
                ORDER BY
                    version.documento_id,
                    version.numero_versao DESC,
                    version.importado_em DESC,
                    version.id DESC
            ), base_transactions AS (
                SELECT
                    transaction.id,
                    transaction.valor,
                    transaction.tipo,
                    transaction.categoria_efetiva AS category,
                    transaction.parcela_atual,
                    transaction.total_parcelas,
                    recurrence.id AS recurrence_id
                FROM spend_label.transacoes_categorizadas AS transaction
                JOIN reference_versions AS version
                  ON version.id = transaction.versao_id
                LEFT JOIN spend_label.recorrencias_transacao AS recurrence
                  ON recurrence.transacao_id = transaction.id
                 AND recurrence.ativa
            ), values AS (
                SELECT
                    version.month_start,
                    'credit_card'::text AS source,
                    transaction.categoria_efetiva AS category,
                    'invoice_actual'::text AS value_kind,
                    SUM(transaction.valor) AS total
                FROM actual_versions AS version
                JOIN spend_label.transacoes_categorizadas AS transaction
                  ON transaction.versao_id = version.id
                GROUP BY version.month_start, transaction.categoria_efetiva

                UNION ALL

                SELECT
                    requested.month_start,
                    'credit_card'::text,
                    base.category,
                    'card_projected'::text,
                    SUM(base.valor)
                FROM requested_months AS requested
                CROSS JOIN latest_reference AS reference
                JOIN base_transactions AS base ON TRUE
                CROSS JOIN LATERAL GENERATE_SERIES(
                    1,
                    GREATEST(
                        COALESCE(base.total_parcelas, 0)
                            - COALESCE(base.parcela_atual, 0),
                        0
                    )
                ) AS installment(number)
                WHERE requested.month_start = (
                    reference.month_start
                    + MAKE_INTERVAL(months => installment.number)
                )::date
                  AND base.tipo = 'compra'
                  AND base.valor > 0
                  AND base.parcela_atual IS NOT NULL
                  AND base.total_parcelas IS NOT NULL
                  AND base.recurrence_id IS NULL
                GROUP BY requested.month_start, base.category

                UNION ALL

                SELECT
                    requested.month_start,
                    'credit_card'::text,
                    transaction.categoria_efetiva,
                    'card_projected'::text,
                    SUM(transaction.valor)
                FROM requested_months AS requested
                CROSS JOIN latest_reference AS reference
                JOIN spend_label.recorrencias_transacao AS recurrence
                  ON recurrence.ativa
                JOIN spend_label.transacoes_categorizadas AS transaction
                  ON transaction.id = recurrence.transacao_id
                WHERE requested.month_start > reference.month_start
                  AND transaction.tipo = 'compra'
                  AND transaction.valor > 0
                  AND (
                      recurrence.modo = 'unlimited'
                      OR requested.month_start <= recurrence.fim_mes
                  )
                GROUP BY requested.month_start, transaction.categoria_efetiva

                UNION ALL

                SELECT
                    requested.month_start,
                    CASE
                        WHEN manual.meio_pagamento = 'credito'
                        THEN 'credit_card'::text
                        ELSE 'other_transactions'::text
                    END,
                    category.slug,
                    CASE manual.tipo_lancamento
                        WHEN 'actual' THEN 'manual_actual'::text
                        ELSE 'manual_projected'::text
                    END,
                    SUM(manual.valor)
                FROM requested_months AS requested
                JOIN cash_flow.lancamentos_manuais AS manual
                  ON manual.ativo
                 AND (
                     manual.mes_referencia = requested.month_start
                     OR (
                         manual.mes_referencia < requested.month_start
                         AND EXISTS (
                             SELECT 1
                             FROM cash_flow.recorrencias_lancamento_manual
                                 AS recurrence
                             WHERE recurrence.lancamento_id = manual.id
                               AND recurrence.ativa
                               AND (
                                   recurrence.modo = 'unlimited'
                                   OR requested.month_start
                                      <= recurrence.fim_mes
                               )
                         )
                     )
                 )
                JOIN spend_label.categorias AS category
                  ON category.id = manual.categoria_id
                GROUP BY
                    requested.month_start,
                    manual.meio_pagamento,
                    category.slug,
                    manual.tipo_lancamento
            )
            SELECT
                TO_CHAR(month_start, 'YYYY-MM') AS month,
                source,
                category,
                value_kind,
                SUM(total) AS total
            FROM values
            GROUP BY month_start, source, category, value_kind
            ORDER BY month_start, source, category, value_kind
            """,
            (month_starts,),
        )
        return cursor.fetchall()

    @staticmethod
    def _raw_values(requested_months: list[str], rows: list[tuple]) -> dict[str, dict[str, dict[str, dict[str, Decimal]]]]:
        raw = {
            month: {
                kind: {source: {} for source in SOURCES}
                for kind in VALUE_KINDS
            }
            for month in requested_months
        }
        for month, source, category, value_kind, total in rows:
            raw[month][value_kind][source][category] = Decimal(total)
        return raw

    @classmethod
    def _build_month(cls, *, month: str, requested_kind: DataKind, metadata: dict[str, Any], raw: dict[str, dict[str, dict[str, Decimal]]], reference_month: str | None) -> dict[str, Any]:
        sources = {
            source: cls._build_source(
                month=month,
                source=source,
                requested_kind=requested_kind,
                metadata=metadata,
                raw=raw,
            )
            for source in SOURCES
        }
        totals = [source["total"] for source in sources.values()]
        total = (
            sum(totals, start=Decimal("0"))
            if all(value is not None for value in totals)
            else None
        )
        return {
            "month": month,
            "data_kind": requested_kind,
            "reference_month": reference_month,
            "total": total,
            "sources": sources,
        }

    @classmethod
    def _build_source(cls, *, month: str, source: str, requested_kind: DataKind, metadata: dict[str, Any], raw: dict[str, dict[str, dict[str, Decimal]]]) -> dict[str, Any]:
        reference_month = metadata["reference_month"]
        if requested_kind == "actual":
            return cls._actual_source(month, source, metadata, raw)
        if requested_kind == "projected":
            return cls._projected_source(month, source, metadata, raw)

        if source == "credit_card" and metadata["invoice_exists"]:
            return cls._actual_source(month, source, metadata, raw)
        if source == "other_transactions" and (
            reference_month is None or month <= reference_month
        ):
            return cls._actual_source(month, source, metadata, raw)
        if reference_month is not None and month > reference_month:
            return cls._projected_source(month, source, metadata, raw)
        return cls._unavailable("data_unavailable")

    @classmethod
    def _actual_source(cls, month: str, source: str, metadata: dict[str, Any], raw: dict[str, dict[str, dict[str, Decimal]]]) -> dict[str, Any]:
        if month > metadata["current_month"]:
            return cls._unavailable("future_period_not_actual")

        if source == "credit_card":
            if not metadata["invoice_exists"]:
                return cls._unavailable("invoice_not_imported")
            categories = raw["invoice_actual"][source]
        else:
            categories = raw["manual_actual"][source]

        status = (
            "partial_month"
            if month == metadata["current_month"]
            else "available"
        )
        return cls._available("actual", status, categories)

    @classmethod
    def _projected_source(cls, month: str, source: str, metadata: dict[str, Any], raw: dict[str, dict[str, dict[str, Decimal]]]) -> dict[str, Any]:
        reference_month = metadata["reference_month"]
        if reference_month is None:
            return cls._unavailable("projection_reference_unavailable")
        if month <= reference_month:
            return cls._unavailable("projection_not_applicable")

        categories: dict[str, Decimal] = {}
        kinds = ["manual_actual", "manual_projected"]
        if source == "credit_card":
            kinds.insert(0, "card_projected")
        for kind in kinds:
            for category, total in raw[kind][source].items():
                categories[category] = categories.get(
                    category, Decimal("0")
                ) + total
        return cls._available("projected", "projected", categories)

    @staticmethod
    def _available(data_kind: str, status: str, categories: dict[str, Decimal]) -> dict[str, Any]:
        return {
            "data_kind": data_kind,
            "status": status,
            "data_found": bool(categories),
            "total": sum(categories.values(), start=Decimal("0")),
            "categories": categories,
        }

    @staticmethod
    def _unavailable(status: str) -> dict[str, Any]:
        return {
            "data_kind": None,
            "status": status,
            "data_found": False,
            "total": None,
            "categories": {},
        }

