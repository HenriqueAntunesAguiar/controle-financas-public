"""Casos de uso do fluxo de caixa local."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi_app.application.ports import AuditLogPort, CashFlowRepositoryPort
from fastapi_app.domain import ImportUnavailableError, InvalidInputError, NotFoundError


PAYMENT_METHODS = {"credito", "pix", "debito", "dinheiro", "transferencia", "outro"}
EXPENSE_TYPES = {"actual", "planned"}
RECURRENCE_MODES = {"none", "unlimited", "until"}


class CashFlowUseCases:
    def __init__(self, repository: CashFlowRepositoryPort, audit: AuditLogPort):
        self.repository = repository
        self.audit = audit

    @staticmethod
    def _month(value: str) -> str:
        try:
            return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
        except ValueError as exc:
            raise InvalidInputError("Mês de referência inválido.") from exc

    @staticmethod
    def _money(value: str | Decimal, field: str, *, positive: bool = False) -> Decimal:
        try:
            amount = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise InvalidInputError(f"{field} inválido.") from exc
        if (positive and amount <= 0) or (not positive and amount < 0):
            raise InvalidInputError(f"{field} inválido.")
        return amount

    @staticmethod
    def _database_call(callback):
        try:
            return callback()
        except (InvalidInputError, NotFoundError):
            raise
        except Exception as exc:
            raise ImportUnavailableError(
                "O fluxo de caixa está temporariamente indisponível."
            ) from exc

    def _recurrence(self, mode: str, end_month: str | None, *, start_month: str | None = None) -> tuple[str, str | None]:
        if mode not in RECURRENCE_MODES:
            raise InvalidInputError("Tipo de recorrência inválido.")
        normalized_end = None
        if mode == "until":
            try:
                normalized_end = self._month(end_month or "")
            except InvalidInputError as exc:
                raise InvalidInputError("Informe o mês final da recorrência.") from exc
            if start_month is not None and normalized_end < start_month:
                raise InvalidInputError(
                    "O fim da recorrência não pode ser anterior ao lançamento."
                )
        return mode, normalized_end

    @staticmethod
    def _serialize_money(data: dict[str, Any]) -> dict[str, Any]:
        return {
            key: format(value, ".2f") if isinstance(value, Decimal) else value
            for key, value in data.items()
        }

    def create_card_forecast(self, month: str, description: str, amount: str, category_slug: str) -> dict[str, Any]:
        normalized_month = self._month(month)
        latest_month = self._database_call(self.repository.latest_invoice_month)
        if latest_month is None:
            raise InvalidInputError(
                "Importe uma fatura-base antes de criar uma simulação futura."
            )
        if normalized_month <= latest_month:
            raise InvalidInputError(
                "O gasto previsto deve pertencer a um mês posterior à última fatura."
            )
        cleaned_description = " ".join(description.split()).strip()
        if not 2 <= len(cleaned_description) <= 180:
            raise InvalidInputError("A descrição deve ter entre 2 e 180 caracteres.")
        if not category_slug or len(category_slug) > 50:
            raise InvalidInputError("Categoria inválida.")
        created = self._database_call(
            lambda: self.repository.create_card_forecast(
                normalized_month,
                cleaned_description,
                self._money(amount, "Valor", positive=True),
                category_slug,
            )
        )
        if not created:
            raise NotFoundError("Categoria não encontrada.")
        self.audit.emit(
            "cash_flow.card_forecast_created",
            component="cash_flow",
            outcome="success",
        )
        return self._serialize_money(created)

    def card_forecasts(self, month: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise InvalidInputError("Limite inválido.")
        normalized_month = self._month(month) if month else None
        rows = self._database_call(
            lambda: self.repository.list_card_forecasts(normalized_month, limit)
        )
        return [self._serialize_money(row) for row in rows]

    def remove_card_forecast(self, forecast_id: int) -> None:
        if forecast_id <= 0:
            raise InvalidInputError("Gasto previsto inválido.")
        if not self._database_call(
            lambda: self.repository.remove_card_forecast(forecast_id)
        ):
            raise NotFoundError("Gasto previsto não encontrado.")
        self.audit.emit(
            "cash_flow.card_forecast_removed",
            component="cash_flow",
            outcome="success",
        )

    def create_expense(self, month: str, description: str, amount: str, category_slug: str, payment_method: str, expense_type: str, recurrence_mode: str = "none", recurrence_end_month: str | None = None) -> dict[str, Any]:
        normalized_month = self._month(month)
        normalized_mode, normalized_end = self._recurrence(
            recurrence_mode,
            recurrence_end_month,
            start_month=normalized_month,
        )
        cleaned_description = " ".join(description.split()).strip()
        if not 2 <= len(cleaned_description) <= 180:
            raise InvalidInputError("A descrição deve ter entre 2 e 180 caracteres.")
        if payment_method not in PAYMENT_METHODS:
            raise InvalidInputError("Meio de pagamento inválido.")
        if expense_type not in EXPENSE_TYPES:
            raise InvalidInputError("Situação do lançamento inválida.")
        if not category_slug or len(category_slug) > 50:
            raise InvalidInputError("Categoria inválida.")
        created = self._database_call(
            lambda: self.repository.create_expense(
                normalized_month,
                cleaned_description,
                self._money(amount, "Valor", positive=True),
                category_slug,
                payment_method,
                expense_type,
                normalized_mode,
                normalized_end,
            )
        )
        if not created:
            raise NotFoundError("Categoria não encontrada.")
        self.audit.emit("cash_flow.expense_created", component="cash_flow", outcome="success")
        return self._serialize_money(created)

    def expenses(self, month: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200:
            raise InvalidInputError("Limite inválido.")
        normalized_month = self._month(month) if month else None
        rows = self._database_call(
            lambda: self.repository.list_expenses(normalized_month, limit)
        )
        return [self._serialize_money(row) for row in rows]

    def update_expense(self, expense_id: int, month: str, description: str, amount: str, category_slug: str, payment_method: str, expense_type: str, recurrence_mode: str = "none", recurrence_end_month: str | None = None) -> dict[str, Any]:
        if expense_id <= 0:
            raise InvalidInputError("Lançamento inválido.")
        normalized_month = self._month(month)
        normalized_mode, normalized_end = self._recurrence(
            recurrence_mode,
            recurrence_end_month,
            start_month=normalized_month,
        )
        cleaned_description = " ".join(description.split()).strip()
        if not 2 <= len(cleaned_description) <= 180:
            raise InvalidInputError("A descrição deve ter entre 2 e 180 caracteres.")
        if payment_method not in PAYMENT_METHODS:
            raise InvalidInputError("Meio de pagamento inválido.")
        if expense_type not in EXPENSE_TYPES:
            raise InvalidInputError("Situação do lançamento inválida.")
        if not category_slug or len(category_slug) > 50:
            raise InvalidInputError("Categoria inválida.")
        updated = self._database_call(
            lambda: self.repository.update_expense(
                expense_id,
                normalized_month,
                cleaned_description,
                self._money(amount, "Valor", positive=True),
                category_slug,
                payment_method,
                expense_type,
                normalized_mode,
                normalized_end,
            )
        )
        if updated == "not_found":
            raise NotFoundError("Lançamento não encontrado.")
        if updated == "category_not_found":
            raise NotFoundError("Categoria não encontrada.")
        self.audit.emit("cash_flow.expense_updated", component="cash_flow", outcome="success")
        return self._serialize_money(updated)

    def remove_expense(self, expense_id: int) -> None:
        if expense_id <= 0:
            raise InvalidInputError("Lançamento inválido.")
        if not self._database_call(lambda: self.repository.remove_expense(expense_id)):
            raise NotFoundError("Lançamento não encontrado.")
        self.audit.emit("cash_flow.expense_removed", component="cash_flow", outcome="success")

    def set_expense_recurrence(self, expense_id: int, mode: str, end_month: str | None = None) -> None:
        if expense_id <= 0:
            raise InvalidInputError("Lançamento inválido.")
        normalized_mode, normalized_end = self._recurrence(mode, end_month)
        result = self._database_call(
            lambda: self.repository.set_expense_recurrence(
                expense_id,
                normalized_mode,
                normalized_end,
            )
        )
        if result == "not_found":
            raise NotFoundError("Lançamento não encontrado.")
        if result == "invalid_end":
            raise InvalidInputError(
                "O fim da recorrência não pode ser anterior ao lançamento."
            )
        self.audit.emit(
            "cash_flow.expense_recurrence_updated",
            component="cash_flow",
            outcome=normalized_mode,
        )

    def monthly_summary(self, month: str, include_manual: bool = True) -> dict[str, Any]:
        result = self._database_call(
            lambda: self.repository.get_monthly_summary(
                self._month(month), include_manual
            )
        )
        return self._serialize_money(result)

    def save_monthly_summary(self, month: str, income: str, saved_base: str) -> dict[str, Any]:
        normalized_month = self._month(month)
        result = self._database_call(
            lambda: self.repository.save_monthly_summary(
                normalized_month,
                self._money(income, "Rendimento"),
                self._money(saved_base, "Valor guardado"),
            )
        )
        self.audit.emit("cash_flow.summary_saved", component="cash_flow", outcome="success")
        return self._serialize_money(result)

    def apply_result(self, month: str) -> dict[str, Any]:
        result = self._database_call(
            lambda: self.repository.apply_monthly_result(self._month(month))
        )
        self.audit.emit("cash_flow.result_applied", component="cash_flow", outcome="success")
        return self._serialize_money(result)
