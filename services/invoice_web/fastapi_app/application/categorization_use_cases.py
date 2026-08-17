"""Regras de categorização sem dependência de HTTP ou PostgreSQL."""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi_app.application.ports import AuditLogPort, CategorizationRepositoryPort
from fastapi_app.domain import ImportUnavailableError, InvalidInputError, NotFoundError


SLUG_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
MERCHANT_ID_RE = re.compile(r"^est_[a-f0-9]{12}$")


class CategorizationUseCases:
    def __init__(self, repository: CategorizationRepositoryPort, audit: AuditLogPort):
        self.repository = repository
        self.audit = audit

    @staticmethod
    def _database_call(callback):
        try:
            return callback()
        except (InvalidInputError, NotFoundError):
            raise
        except Exception as exc:
            raise ImportUnavailableError(
                "A categorização está temporariamente indisponível."
            ) from exc

    def categories(self) -> list[dict[str, Any]]:
        return self._database_call(self.repository.list_categories)

    def create_category(self, name: str) -> dict[str, Any]:
        cleaned_name = " ".join(name.split()).strip()
        if not 2 <= len(cleaned_name) <= 100:
            raise InvalidInputError("O nome da categoria deve ter entre 2 e 100 caracteres.")
        ascii_name = unicodedata.normalize("NFKD", cleaned_name).encode(
            "ascii", "ignore"
        ).decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:50]
        if not slug or not SLUG_RE.fullmatch(slug):
            raise InvalidInputError("Não foi possível gerar um identificador para a categoria.")
        category = self._database_call(
            lambda: self.repository.create_category(slug, cleaned_name)
        )
        self.audit.emit(
            "categorization.category_created",
            component="spend_label",
            outcome="success",
        )
        return category

    def transactions(self, limit: int = 100, offset: int = 0, query: str = "", category_slug: str = "", review_status: str = "all", sort_field: str = "date", sort_direction: str = "desc") -> dict[str, Any]:
        if not 1 <= limit <= 200 or offset < 0:
            raise InvalidInputError("Paginação inválida.")
        cleaned_query = " ".join(query.split()).strip()[:120]
        if category_slug and not SLUG_RE.fullmatch(category_slug):
            raise InvalidInputError("Filtro de categoria inválido.")
        if review_status not in {"all", "pending", "confirmed", "suggested"}:
            raise InvalidInputError("Filtro de revisão inválido.")
        if sort_field not in {"date", "merchant", "amount", "category", "source"}:
            raise InvalidInputError("Campo de ordenação inválido.")
        if sort_direction not in {"asc", "desc"}:
            raise InvalidInputError("Direção de ordenação inválida.")
        return self._database_call(
            lambda: self.repository.list_transactions(
                limit,
                offset,
                cleaned_query,
                category_slug,
                review_status,
                sort_field,
                sort_direction,
            )
        )

    def merchants(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        normalized_query = " ".join(query.split())[:120]
        if not 1 <= limit <= 50:
            raise InvalidInputError("Limite inválido.")
        return self._database_call(
            lambda: self.repository.list_merchants(normalized_query, limit)
        )

    def categorize(self, transaction_id: int, category_slug: str, scope: str, merchant_name: str | None = None) -> None:
        if transaction_id <= 0:
            raise InvalidInputError("Transação inválida.")
        if not SLUG_RE.fullmatch(category_slug):
            raise InvalidInputError("Categoria inválida.")
        if scope not in {"transaction", "merchant"}:
            raise InvalidInputError("Escopo de categorização inválido.")
        cleaned_name = " ".join((merchant_name or "").split()).strip() or None
        if cleaned_name is not None and len(cleaned_name) > 120:
            raise InvalidInputError("O nome do estabelecimento excede 120 caracteres.")
        started = time.perf_counter()
        updated = self._database_call(
            lambda: self.repository.categorize(
                transaction_id, category_slug, scope, cleaned_name
            )
        )
        if not updated:
            raise NotFoundError("Transação ou categoria não encontrada.")
        self.audit.emit(
            "categorization.confirmed",
            component="spend_label",
            outcome=scope,
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def merge_alias(self, alias_hash: str, merchant_id: str) -> None:
        if not MERCHANT_ID_RE.fullmatch(alias_hash) or not MERCHANT_ID_RE.fullmatch(
            merchant_id
        ):
            raise InvalidInputError("Identificador de estabelecimento inválido.")
        merged = self._database_call(
            lambda: self.repository.merge_alias(alias_hash, merchant_id)
        )
        if not merged:
            raise NotFoundError("Alias ou estabelecimento não encontrado.")
        self.audit.emit(
            "categorization.alias_merged",
            component="spend_label",
            outcome="success",
        )

    def set_recurrence(self, transaction_id: int, mode: str, end_month: str | None = None) -> None:
        if transaction_id <= 0:
            raise InvalidInputError("Transação inválida.")
        if mode not in {"none", "unlimited", "until"}:
            raise InvalidInputError("Tipo de recorrência inválido.")
        normalized_end = None
        if mode == "until":
            try:
                normalized_end = datetime.strptime(end_month or "", "%Y-%m").strftime(
                    "%Y-%m"
                )
            except ValueError as exc:
                raise InvalidInputError("Informe o mês final da recorrência.") from exc
        updated = self._database_call(
            lambda: self.repository.set_recurrence(
                transaction_id,
                mode,
                normalized_end,
            )
        )
        if not updated:
            raise NotFoundError("Transação não encontrada.")
        self.audit.emit(
            "categorization.recurrence_updated",
            component="spend_label",
            outcome=mode,
        )

    def monthly(self, months: int = 12, include_card: bool = True, include_manual: bool = True, include_actual: bool = True, include_projected: bool = True, include_expense_income: bool = False) -> dict[str, Any]:
        if not 1 <= months <= 36:
            raise InvalidInputError("Período inválido.")
        projection = self._database_call(
            lambda: self.repository.monthly_totals(
                months,
                include_card,
                include_manual,
                include_actual,
                include_projected,
                include_expense_income,
            )
        )
        expense_totals: dict[str, Decimal] = {}
        for row in projection["series"]:
            month = row["month"]
            expense_totals[month] = expense_totals.get(month, Decimal("0")) + Decimal(
                str(row["total"])
            )
        saved_balance = Decimal(str(projection.get("saved_base", 0)))
        expense_income_projection = []
        for row in projection.get("monthly_income", []):
            expenses = expense_totals.get(row["month"], Decimal("0"))
            income = Decimal(str(row["income"]))
            movement = income - expenses
            saved_balance += movement
            expense_income_projection.append({
                "month": row["month"],
                "expenses": format(expenses, ".2f"),
                "income": format(income, ".2f"),
                "total": format(movement, ".2f"),
                "saved_balance": format(saved_balance, ".2f"),
            })
        return {
            "months": months,
            "include_card": include_card,
            "include_manual": include_manual,
            "include_actual": include_actual,
            "include_projected": include_projected,
            "include_expense_income": include_expense_income,
            "reference_month": projection["reference_month"],
            "saved_base": format(Decimal(str(projection.get("saved_base", 0))), ".2f"),
            "expense_income_projection": expense_income_projection,
            "series": [
                {
                    **row,
                    "total": format(Decimal(str(row["total"])), ".2f"),
                }
                for row in projection["series"]
            ],
        }

    def monthly_breakdown(self, month: str) -> dict[str, Any]:
        try:
            normalized_month = datetime.strptime(month, "%Y-%m").strftime("%Y-%m")
        except ValueError as exc:
            raise InvalidInputError("Mês de detalhamento inválido.") from exc
        result = self._database_call(
            lambda: self.repository.monthly_breakdown(normalized_month)
        )
        reference_month = result.get("reference_month")
        if reference_month and normalized_month < reference_month:
            raise InvalidInputError(
                "O detalhamento deve partir do último mês fechado."
            )
        entries = [
            {
                **entry,
                "amount": format(Decimal(str(entry["amount"])), ".2f"),
            }
            for entry in result.get("entries", [])
        ]
        grouped: dict[str, dict[str, Any]] = {}
        for entry in entries:
            category = grouped.setdefault(
                entry["category"],
                {
                    "category": entry["category"],
                    "category_name": entry["category_name"],
                    "total": Decimal("0"),
                    "count": 0,
                },
            )
            category["total"] += Decimal(entry["amount"])
            category["count"] += 1
        categories = [
            {**category, "total": format(category["total"], ".2f")}
            for category in sorted(
                grouped.values(),
                key=lambda item: (-item["total"], item["category_name"]),
            )
        ]
        return {
            "month": normalized_month,
            "reference_month": reference_month,
            "total": format(
                sum((Decimal(entry["amount"]) for entry in entries), Decimal("0")),
                ".2f",
            ),
            "categories": categories,
            "entries": entries,
        }
