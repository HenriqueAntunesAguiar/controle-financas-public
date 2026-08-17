"""Adaptador HTTP: traduz FastAPI para os casos de uso."""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.templating import Jinja2Templates

from fastapi_app.application import (
    CashFlowUseCases,
    CategorizationUseCases,
    DiagnosticsUseCase,
    InvoiceUseCases,
)
from fastapi_app.domain import ForbiddenError
from fastapi_app.application.ports import AssistantPort


router = APIRouter()
templates = Jinja2Templates(
    directory=Path(__file__).resolve().parents[3] / "views" / "templates"
)


class ProcessBody(BaseModel):
    senha: str | None = Field(default=None, max_length=256)


class CategorizationBody(BaseModel):
    category_slug: str = Field(min_length=1, max_length=50)
    scope: Literal["transaction", "merchant"]
    merchant_name: str | None = Field(default=None, max_length=120)


class CategoryCreateBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class AliasMergeBody(BaseModel):
    merchant_id: str = Field(min_length=1, max_length=32)


class RecurrenceBody(BaseModel):
    mode: Literal["none", "unlimited", "until"]
    end_month: str | None = Field(default=None, max_length=7)


class ManualExpenseBody(BaseModel):
    month: str = Field(min_length=7, max_length=7)
    description: str = Field(min_length=2, max_length=180)
    amount: str = Field(min_length=1, max_length=30)
    category_slug: str = Field(min_length=1, max_length=50)
    payment_method: Literal[
        "credito", "pix", "debito", "dinheiro", "transferencia", "outro"
    ]
    expense_type: Literal["actual", "planned"] = "actual"
    recurrence_mode: Literal["none", "unlimited", "until"] = "none"
    recurrence_end_month: str | None = Field(default=None, max_length=7)


class CardForecastBody(BaseModel):
    month: str = Field(min_length=7, max_length=7)
    description: str = Field(min_length=2, max_length=180)
    amount: str = Field(min_length=1, max_length=30)
    category_slug: str = Field(min_length=1, max_length=50)


class MonthlySummaryBody(BaseModel):
    income: str = Field(min_length=1, max_length=30)
    saved_base: str = Field(min_length=1, max_length=30)


class AssistantChatBody(BaseModel):
    thread_id: UUID
    message: str = Field(min_length=1, max_length=2000)


class AssistantDecisionBody(BaseModel):
    thread_id: UUID
    interrupt_id: str = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]


def invoices(request: Request) -> InvoiceUseCases:
    return request.app.state.container.invoices


def diagnostics(request: Request) -> DiagnosticsUseCase:
    return request.app.state.container.diagnostics


def categorization(request: Request) -> CategorizationUseCases:
    return request.app.state.container.categorization


def cash_flow(request: Request) -> CashFlowUseCases:
    return request.app.state.container.cash_flow


def assistant(request: Request) -> AssistantPort:
    return request.app.state.container.assistant


def csrf(request: Request) -> None:
    expected = request.session.get("csrf", "")
    received = request.headers.get("X-CSRF-Token", "")
    if not expected or not hmac.compare_digest(expected, received):
        raise ForbiddenError("Sessao expirada. Recarregue a pagina.")


@router.get("/", response_class=HTMLResponse)
def home(request: Request, use_cases: InvoiceUseCases = Depends(invoices)):
    token = request.session.get("csrf")
    if token is None:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"csrf_token": token, **use_cases.dashboard()},
    )


@router.post("/api/invoices")
async def upload(invoice: Annotated[UploadFile, File()], name: Annotated[str, Form(max_length=120)], reference_date: Annotated[str, Form()], use_cases: InvoiceUseCases = Depends(invoices), _csrf: None = Depends(csrf)):
    async def chunks():
        while chunk := await invoice.read(1024 * 1024):
            yield chunk

    try:
        invoice_id = await use_cases.register(
            name, invoice.filename or "", reference_date, chunks()
        )
    finally:
        await invoice.close()
    return JSONResponse(
        {"message": "Fatura registrada localmente.", "id": invoice_id},
        status_code=201,
    )


@router.post("/api/invoices/{invoice_id}/process")
async def process(invoice_id: str, body: ProcessBody, use_cases: InvoiceUseCases = Depends(invoices), _csrf: None = Depends(csrf)):
    result = await run_in_threadpool(use_cases.process, invoice_id, body.senha or None)
    return {
        "message": (
            f"Versao {result.version} criada com {result.transactions} transacoes."
            + (
                " Foram encontradas divergencias; revise o JSON antes de importar."
                if result.requires_review
                else " Totais conferidos com a fatura."
            )
        )
    }


@router.post("/api/invoices/{invoice_id}/import")
async def import_invoice(invoice_id: str, use_cases: InvoiceUseCases = Depends(invoices), _csrf: None = Depends(csrf)):
    existing = await run_in_threadpool(use_cases.import_latest, invoice_id)
    return {
        "message": (
            "Versao ja existente no PostgreSQL."
            if existing
            else "Versao importada para o PostgreSQL."
        )
    }


@router.post("/api/invoices/{invoice_id}/approve")
async def approve_review(invoice_id: str, use_cases: InvoiceUseCases = Depends(invoices), _csrf: None = Depends(csrf)):
    await run_in_threadpool(use_cases.approve_latest, invoice_id)
    return {"message": "Versao aprovada manualmente e liberada para importacao."}


@router.get("/api/categories")
async def categories(use_case: CategorizationUseCases = Depends(categorization)):
    return {"items": await run_in_threadpool(use_case.categories)}


@router.post("/api/categories", status_code=201)
async def create_category(body: CategoryCreateBody, use_case: CategorizationUseCases = Depends(categorization), _csrf: None = Depends(csrf)):
    category = await run_in_threadpool(use_case.create_category, body.name)
    return {"item": category, "message": "Categoria disponível para classificação."}


@router.get("/api/transactions")
async def transactions(limit: Annotated[int, Query(ge=1, le=200)] = 100, offset: Annotated[int, Query(ge=0)] = 0, q: Annotated[str, Query(max_length=120)] = "", category: Annotated[str, Query(max_length=50)] = "", status: Literal["all", "pending", "confirmed", "suggested"] = "all", sort: Literal["date", "merchant", "amount", "category", "source"] = "date", direction: Literal["asc", "desc"] = "desc", use_case: CategorizationUseCases = Depends(categorization)):
    return await run_in_threadpool(
        use_case.transactions, limit, offset, q, category, status, sort, direction
    )


@router.put("/api/transactions/{transaction_id}/category")
async def categorize_transaction(transaction_id: int, body: CategorizationBody, use_case: CategorizationUseCases = Depends(categorization), _csrf: None = Depends(csrf)):
    await run_in_threadpool(
        use_case.categorize,
        transaction_id,
        body.category_slug,
        body.scope,
        body.merchant_name,
    )
    return {"message": "Categoria confirmada e adicionada à base de aprendizado."}


@router.get("/api/merchants")
async def merchants(query: Annotated[str, Query(max_length=120)] = "", limit: Annotated[int, Query(ge=1, le=50)] = 20, use_case: CategorizationUseCases = Depends(categorization)):
    return {"items": await run_in_threadpool(use_case.merchants, query, limit)}


@router.post("/api/aliases/{alias_hash}/merge")
async def merge_alias(alias_hash: str, body: AliasMergeBody, use_case: CategorizationUseCases = Depends(categorization), _csrf: None = Depends(csrf)):
    await run_in_threadpool(use_case.merge_alias, alias_hash, body.merchant_id)
    return {"message": "Alias associado ao estabelecimento."}


@router.put("/api/transactions/{transaction_id}/recurrence")
async def set_transaction_recurrence(transaction_id: int, body: RecurrenceBody, use_case: CategorizationUseCases = Depends(categorization), _csrf: None = Depends(csrf)):
    await run_in_threadpool(
        use_case.set_recurrence,
        transaction_id,
        body.mode,
        body.end_month,
    )
    return {"message": "Recorrência atualizada e aplicada à projeção."}


@router.get("/api/analytics/monthly")
async def monthly_analytics(months: Annotated[int, Query(ge=1, le=36)] = 12, include_card: bool = True, include_manual: bool = True, include_actual: bool = True, include_projected: bool = True, include_expense_income: bool = False, use_case: CategorizationUseCases = Depends(categorization)):
    return await run_in_threadpool(
        use_case.monthly,
        months,
        include_card,
        include_manual,
        include_actual,
        include_projected,
        include_expense_income,
    )


@router.get("/api/analytics/monthly/{month}/breakdown")
async def monthly_analytics_breakdown(month: str, use_case: CategorizationUseCases = Depends(categorization)):
    return await run_in_threadpool(use_case.monthly_breakdown, month)


@router.get("/api/cash-flow/expenses")
async def manual_expenses(month: Annotated[str | None, Query(min_length=7, max_length=7)] = None, limit: Annotated[int, Query(ge=1, le=200)] = 100, use_case: CashFlowUseCases = Depends(cash_flow)):
    return {"items": await run_in_threadpool(use_case.expenses, month, limit)}


@router.get("/api/cash-flow/card-forecasts")
async def card_forecasts(month: Annotated[str | None, Query(min_length=7, max_length=7)] = None, limit: Annotated[int, Query(ge=1, le=200)] = 100, use_case: CashFlowUseCases = Depends(cash_flow)):
    return {
        "items": await run_in_threadpool(use_case.card_forecasts, month, limit)
    }


@router.post("/api/cash-flow/card-forecasts", status_code=201)
async def create_card_forecast(body: CardForecastBody, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    item = await run_in_threadpool(
        use_case.create_card_forecast,
        body.month,
        body.description,
        body.amount,
        body.category_slug,
    )
    return {"item": item, "message": "Gasto incluído na simulação do cartão."}


@router.delete("/api/cash-flow/card-forecasts/{forecast_id}")
async def remove_card_forecast(forecast_id: int, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    await run_in_threadpool(use_case.remove_card_forecast, forecast_id)
    return {"message": "Gasto previsto removido da simulação."}


@router.post("/api/cash-flow/expenses", status_code=201)
async def create_manual_expense(body: ManualExpenseBody, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    item = await run_in_threadpool(
        use_case.create_expense,
        body.month,
        body.description,
        body.amount,
        body.category_slug,
        body.payment_method,
        body.expense_type,
        body.recurrence_mode,
        body.recurrence_end_month,
    )
    return {"item": item, "message": "Lançamento adicionado ao fluxo de caixa."}


@router.put("/api/cash-flow/expenses/{expense_id}")
async def update_manual_expense(expense_id: int, body: ManualExpenseBody, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    item = await run_in_threadpool(
        use_case.update_expense,
        expense_id,
        body.month,
        body.description,
        body.amount,
        body.category_slug,
        body.payment_method,
        body.expense_type,
        body.recurrence_mode,
        body.recurrence_end_month,
    )
    return {"item": item, "message": "Lançamento atualizado."}


@router.delete("/api/cash-flow/expenses/{expense_id}")
async def remove_manual_expense(expense_id: int, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    await run_in_threadpool(use_case.remove_expense, expense_id)
    return {"message": "Lançamento removido."}


@router.put("/api/cash-flow/expenses/{expense_id}/recurrence")
async def set_manual_expense_recurrence(expense_id: int, body: RecurrenceBody, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    await run_in_threadpool(
        use_case.set_expense_recurrence,
        expense_id,
        body.mode,
        body.end_month,
    )
    return {"message": "Recorrência do lançamento atualizada na projeção."}


@router.get("/api/cash-flow/monthly/{month}")
async def monthly_cash_flow(month: str, include_manual: bool = True, use_case: CashFlowUseCases = Depends(cash_flow)):
    return await run_in_threadpool(use_case.monthly_summary, month, include_manual)


@router.put("/api/cash-flow/monthly/{month}")
async def save_monthly_cash_flow(month: str, body: MonthlySummaryBody, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    result = await run_in_threadpool(
        use_case.save_monthly_summary, month, body.income, body.saved_base
    )
    return {"item": result, "message": "Resumo mensal salvo."}


@router.post("/api/cash-flow/monthly/{month}/apply-result")
async def apply_monthly_result(month: str, use_case: CashFlowUseCases = Depends(cash_flow), _csrf: None = Depends(csrf)):
    result = await run_in_threadpool(use_case.apply_result, month)
    return {"item": result, "message": "Resultado mensal aplicado ao guardado."}


@router.post("/api/assistant/chat")
async def assistant_chat(body: AssistantChatBody, gateway: AssistantPort = Depends(assistant), _csrf: None = Depends(csrf)):
    return await run_in_threadpool(gateway.chat, str(body.thread_id), body.message.strip())


@router.post("/api/assistant/chat/decision")
async def assistant_decision(body: AssistantDecisionBody, gateway: AssistantPort = Depends(assistant), _csrf: None = Depends(csrf)):
    return await run_in_threadpool(gateway.decide, str(body.thread_id), body.interrupt_id, body.decision)


@router.get("/health/live")
def liveness():
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(use_case: DiagnosticsUseCase = Depends(diagnostics)):
    result = await run_in_threadpool(use_case.connections)
    return JSONResponse(result, status_code=200 if result["status"] == "ok" else 503)


@router.get("/api/system/connections")
async def connection_status(use_case: DiagnosticsUseCase = Depends(diagnostics)):
    return await run_in_threadpool(use_case.connections)


@router.get("/api/system/logs")
def recent_logs(limit: Annotated[int, Query(ge=1, le=200)] = 50, use_case: DiagnosticsUseCase = Depends(diagnostics)):
    return {"events": use_case.logs(limit)}
