import io
import re
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from fastapi_app.adapters.outbound.observability import JsonAuditLog
from fastapi_app.adapters.outbound.pdf import parse_transaction_line
from fastapi_app.adapters.outbound.pdf.pdfplumber_invoice_parser import (
    _current_total,
    _extract_table_transactions,
)
from fastapi_app.adapters.outbound.persistence import SQLiteInvoiceRepository
from fastapi_app.main import create_app


class FakeCategorizationRepository:
    def __init__(self):
        self.categorizations = []
        self.merges = []
        self.created_categories = []
        self.last_transaction_filters = None
        self.last_monthly_filters = None
        self.recurrences = []

    def list_categories(self):
        return [
            {"slug": "transporte", "nome": "Transporte", "parent_slug": None},
            {"slug": "outros", "nome": "Outros", "parent_slug": None},
        ]

    def list_transactions(self, limit, offset, query, category_slug, review_status, sort_field, sort_direction):
        self.last_transaction_filters = (
            query,
            category_slug,
            review_status,
            sort_field,
            sort_direction,
        )
        items = [
            {
                "id": 10,
                "data_transacao": "2026-07-26",
                "valor": "42.50",
                "descricao": "CORRIDA FICTICIA",
                "descricao_normalizada": "corrida ficticia",
                "localidade": "Sao Paulo",
                "alias_hash": "est_111111111111",
                "estabelecimento_id": "est_111111111111",
                "estabelecimento_nome": "Corrida ficticia",
                "categoria_efetiva": "outros",
                "categoria_origem": "parser",
                "categoria_sugerida": None,
                "sugestao_confianca": None,
                "sugestao_modelo_versao": None,
                "parcela_atual": None,
                "total_parcelas": None,
                "recurrence_mode": None,
                "recurrence_end_month": None,
            }
        ]
        return {"items": items[offset:offset + limit], "total": 1, "limit": limit, "offset": offset}

    def create_category(self, slug, name):
        self.created_categories.append((slug, name))
        return {"slug": slug, "nome": name, "parent_slug": None}

    def list_merchants(self, query, limit):
        return [
            {
                "id": "est_111111111111",
                "nome_canonico": "Corrida ficticia",
                "categoria_padrao": None,
                "categoria_padrao_confirmada": False,
                "aliases": 1,
            }
        ][:limit]

    def categorize(self, transaction_id, category_slug, scope, merchant_name):
        if transaction_id != 10 or category_slug not in {"transporte", "outros"}:
            return False
        self.categorizations.append(
            (transaction_id, category_slug, scope, merchant_name)
        )
        return True

    def merge_alias(self, alias_hash, merchant_id):
        self.merges.append((alias_hash, merchant_id))
        return True

    def set_recurrence(self, transaction_id, mode, end_month):
        if transaction_id != 10:
            return False
        self.recurrences.append((transaction_id, mode, end_month))
        return True

    def monthly_totals(self, months, include_card, include_manual, include_actual, include_projected, include_expense_income):
        self.last_monthly_filters = (
            months,
            include_card,
            include_manual,
            include_actual,
            include_projected,
            include_expense_income,
        )
        return {
            "reference_month": "2026-07",
            "series": [
                {
                    "month": "2026-07",
                    "category": "transporte",
                    "kind": "actual",
                    "total": Decimal("42.50"),
                },
                {
                    "month": "2026-08",
                    "category": "transporte",
                    "kind": "projected",
                    "total": Decimal("42.50"),
                },
            ],
            "monthly_income": [
                {"month": "2026-07", "income": Decimal("100.00")},
                {"month": "2026-08", "income": Decimal("100.00")},
            ] if include_expense_income else [],
            "saved_base": Decimal("1000.00") if include_expense_income else Decimal("0"),
        }

    def monthly_breakdown(self, month):
        return {
            "reference_month": "2026-07",
            "entries": [
                {
                    "entry_id": "invoice-10",
                    "category": "transporte",
                    "category_name": "Transporte",
                    "description": "Corrida fictícia",
                    "amount": Decimal("42.50"),
                    "source_label": "Fatura",
                    "source_group": "card",
                    "kind": "actual" if month == "2026-07" else "projected",
                }
            ],
        }


class FakeCashFlowRepository:
    def __init__(self):
        self.expenses = []
        self.forecasts = []
        self.summary = {
            "month": "2026-07",
            "income": Decimal("5000.00"),
            "saved_base": Decimal("1000.00"),
            "card_expenses": Decimal("2000.00"),
            "manual_expenses": Decimal("500.00"),
            "total_expenses": Decimal("2500.00"),
            "result": Decimal("2500.00"),
            "applied_result": None,
            "saved_total": Decimal("1000.00"),
        }

    def latest_invoice_month(self):
        return "2026-07"

    def create_card_forecast(self, month, description, amount, category_slug):
        item = {
            "id": len(self.forecasts) + 1,
            "month": month,
            "description": description,
            "amount": amount,
            "category_slug": category_slug,
            "category_name": "Educação",
            "covered_by_invoice": False,
        }
        self.forecasts.append(item)
        return item

    def list_card_forecasts(self, month, limit):
        items = self.forecasts
        if month:
            items = [item for item in items if item["month"] == month]
        return items[:limit]

    def remove_card_forecast(self, forecast_id):
        before = len(self.forecasts)
        self.forecasts = [
            item for item in self.forecasts if item["id"] != forecast_id
        ]
        return len(self.forecasts) != before

    def create_expense(self, month, description, amount, category_slug, payment_method, expense_type, recurrence_mode, recurrence_end_month):
        item = {
            "id": len(self.expenses) + 1,
            "month": month,
            "description": description,
            "amount": amount,
            "category_slug": category_slug,
            "category_name": "Educação",
            "payment_method": payment_method,
            "expense_type": expense_type,
            "recurrence_mode": recurrence_mode if recurrence_mode != "none" else None,
            "recurrence_end_month": recurrence_end_month,
        }
        self.expenses.append(item)
        return item

    def list_expenses(self, month, limit):
        items = self.expenses
        if month:
            items = [item for item in items if item["month"] == month]
        return items[:limit]

    def update_expense(self, expense_id, month, description, amount, category_slug, payment_method, expense_type, recurrence_mode, recurrence_end_month):
        item = next((item for item in self.expenses if item["id"] == expense_id), None)
        if item is None:
            return "not_found"
        item.update(
            month=month,
            description=description,
            amount=amount,
            category_slug=category_slug,
            payment_method=payment_method,
            expense_type=expense_type,
            recurrence_mode=recurrence_mode if recurrence_mode != "none" else None,
            recurrence_end_month=recurrence_end_month,
        )
        return item

    def remove_expense(self, expense_id):
        before = len(self.expenses)
        self.expenses = [item for item in self.expenses if item["id"] != expense_id]
        return len(self.expenses) != before

    def set_expense_recurrence(self, expense_id, mode, end_month):
        item = next((item for item in self.expenses if item["id"] == expense_id), None)
        if item is None:
            return "not_found"
        if end_month is not None and end_month < item["month"]:
            return "invalid_end"
        item["recurrence_mode"] = mode if mode != "none" else None
        item["recurrence_end_month"] = end_month
        return "updated"

    def get_monthly_summary(self, month, include_manual=True):
        result = {**self.summary, "month": month, "include_manual": include_manual}
        result["total_expenses"] = result["card_expenses"] + (
            result["manual_expenses"] if include_manual else Decimal("0")
        )
        result["result"] = result["income"] - result["total_expenses"]
        return result

    def save_monthly_summary(self, month, income, saved_base):
        self.summary.update(month=month, income=income, saved_base=saved_base)
        self.summary["result"] = income - self.summary["total_expenses"]
        self.summary["saved_total"] = saved_base + (self.summary["applied_result"] or 0)
        return dict(self.summary)

    def apply_monthly_result(self, month):
        self.summary["month"] = month
        self.summary["applied_result"] = self.summary["result"]
        self.summary["saved_total"] = self.summary["saved_base"] + self.summary["result"]
        return dict(self.summary)


class ParserTests(unittest.TestCase):
    @staticmethod
    def _word(text, x0, x1, top):
        return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 7}

    def test_parseia_linha_ficticia_com_descricao(self):
        transaction = parse_transaction_line(
            "18/07 MERCADO FICTICIO R$ 123,45",
            page_number=2,
            reference_date=date(2026, 8, 1),
            key=b"k" * 32,
        )

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction["valor"], "123.45")
        self.assertEqual(transaction["data_iso"], "2026-07-18")
        self.assertEqual(transaction["descricao"], "MERCADO FICTICIO")
        self.assertEqual(transaction["descricao_normalizada"], "MERCADO FICTICIO")

    def test_remove_marcador_de_parcela_da_descricao(self):
        transaction = parse_transaction_line(
            "26/07 AMAZON BR *A 01/10 102,95",
            page_number=1,
            reference_date=date(2026, 8, 1),
            key=b"k" * 32,
        )

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction["descricao"], "AMAZON BR")
        self.assertEqual(transaction["descricao_normalizada"], "AMAZON BR")
        self.assertEqual(transaction["parcela_atual"], 1)
        self.assertEqual(transaction["total_parcelas"], 10)
        self.assertEqual(transaction["valor"], "102.95")

    def test_extracao_geometrica_ignora_parcelas_futuras(self):
        words = [
            self._word("Lançamentos:", 10, 45, 10),
            self._word("compras", 47, 70, 10),
            self._word("e", 72, 74, 10),
            self._word("saques", 76, 95, 10),
            self._word("DATA", 10, 22, 20),
            self._word("ESTABELECIMENTO", 30, 75, 20),
            self._word("VALOR", 100, 114, 20),
            self._word("EM", 116, 122, 20),
            self._word("R$", 124, 130, 20),
            self._word("26/07", 10, 24, 30),
            self._word("AMAZON", 30, 52, 30),
            self._word("BR", 54, 60, 30),
            self._word("*A", 62, 68, 30),
            self._word("01/10", 70, 84, 30),
            self._word("102,95", 110, 130, 30),
            self._word("vestuário", 30, 52, 39),
            self._word("Sao", 54, 63, 39),
            self._word("Paulo", 65, 78, 39),
            self._word("Total", 10, 25, 50),
            self._word("dos", 27, 35, 50),
            self._word("lançamentos", 37, 67, 50),
            self._word("atuais", 69, 84, 50),
            self._word("102,95", 110, 130, 50),
            self._word("Compras", 10, 30, 60),
            self._word("parceladas", 32, 58, 60),
            self._word("-", 60, 62, 60),
            self._word("próximas", 64, 86, 60),
            self._word("faturas", 88, 104, 60),
            self._word("DATA", 10, 22, 70),
            self._word("ESTABELECIMENTO", 30, 75, 70),
            self._word("VALOR", 100, 114, 70),
            self._word("EM", 116, 122, 70),
            self._word("R$", 124, 130, 70),
            self._word("26/07", 10, 24, 80),
            self._word("AMAZON", 30, 52, 80),
            self._word("BR", 54, 60, 80),
            self._word("02/10", 70, 84, 80),
            self._word("102,86", 110, 130, 80),
        ]

        class FakePage:
            height = 120

            def extract_words(self, **_kwargs):
                return words

        page = FakePage()
        transactions, table_count = _extract_table_transactions(
            page, 1, date(2026, 8, 1), b"k" * 32
        )

        self.assertEqual(table_count, 1)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["descricao"], "AMAZON BR")
        self.assertEqual(transactions[0]["categoria"], "vestuario")
        self.assertEqual(transactions[0]["localidade"], "Sao Paulo")
        self.assertEqual(str(_current_total(page)), "102.95")

    def test_mercado_livre_nao_vira_alimentacao_por_substring(self):
        transaction = parse_transaction_line(
            "07/01 MERCADOLIVRE 98,99",
            page_number=1,
            reference_date=date(2026, 8, 1),
            key=b"k" * 32,
        )
        self.assertEqual(transaction["categoria"], "outros")


class StoreTests(unittest.TestCase):
    def test_preserva_duas_versoes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteInvoiceRepository(Path(directory) / "registry.sqlite3")
            invoice_id = "3c47c7bf-490c-4a0f-bbf8-98a43fc02401"
            store.create(
                invoice_id,
                "Cartao principal",
                "ficticia.pdf",
                "uploads/fatura.pdf",
                "2026-08-01",
            )
            first = store.begin_processing(invoice_id)
            store.finish_processing(
                invoice_id, first["version_number"], "v1.json", "a" * 64, 3, "ready"
            )
            second = store.begin_processing(invoice_id)
            store.finish_processing(
                invoice_id,
                second["version_number"],
                "v2.json",
                "b" * 64,
                4,
                "needs_review",
            )

            invoice = store.list_all()[0]
            self.assertEqual(invoice["name"], "Cartao principal")
            self.assertEqual(invoice["current_version"], 2)
            self.assertEqual(invoice["status"], "needs_review")
            self.assertEqual(len(invoice["versions"]), 2)
            store.approve_latest(invoice_id)
            approved = store.list_all()[0]
            self.assertEqual(approved["status"], "ready")
            self.assertEqual(approved["versions"][0]["status"], "ready")

    def test_migra_registro_antigo_usando_nome_do_arquivo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """
                    CREATE TABLE invoices (
                        id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                        pdf_path TEXT NOT NULL, reference_date TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'received',
                        current_version INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        error_code TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        "9e41de7f-f203-4f3f-b1e5-660797c7ed3c",
                        "fatura-antiga.pdf",
                        "uploads/antiga.pdf",
                        "2026-07-01",
                        "received",
                        0,
                        "2026-07-01T00:00:00+00:00",
                        "2026-07-01T00:00:00+00:00",
                        None,
                    ),
                )
            connection.close()

            store = SQLiteInvoiceRepository(path)
            self.assertEqual(store.list_all()[0]["name"], "fatura-antiga.pdf")


class FakeAssistant:
    def __init__(self):
        self.messages = []
        self.decisions = []

    def chat(self, thread_id, message):
        self.messages.append((thread_id, message))
        return {"thread_id": thread_id, "answer": "Resposta financeira de teste.", "pending_approval": {"id": "interrupt-1", "description": "Adicionar lancamento de teste."}}

    def decide(self, thread_id, interrupt_id, decision):
        self.decisions.append((thread_id, interrupt_id, decision))
        return {"thread_id": thread_id, "answer": "Operacao confirmada.", "pending_approval": None}


class AuditTests(unittest.TestCase):
    def test_descarta_campos_sensiveis_e_desconhecidos(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.jsonl"
            audit = JsonAuditLog(path)
            audit.emit(
                "connection.probe",
                component="postgresql",
                outcome="ok",
                password="segredo-que-nao-pode-aparecer",
                description="estabelecimento privado",
            )

            content = path.read_text(encoding="utf-8")
            self.assertIn('"component":"postgresql"', content)
            self.assertNotIn("segredo-que-nao-pode-aparecer", content)
            self.assertNotIn("estabelecimento privado", content)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.categorization = FakeCategorizationRepository()
        self.cash_flow = FakeCashFlowRepository()
        self.assistant = FakeAssistant()
        self.app = create_app(
            Path(self.temporary.name),
            testing=True,
            categorization_repository=self.categorization,
            cash_flow_repository=self.cash_flow,
            assistant=self.assistant,
        )
        self.client = TestClient(self.app)
        page = self.client.get("/")
        match = re.search(rb'name="csrf-token" content="([^"]+)"', page.content)
        assert match
        self.csrf = match.group(1).decode()

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_pagina_responde(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Fatura Local", response.content)
        self.assertIn("Fatura atual e projeção".encode(), response.content)
        self.assertIn(b'id="chart-actual-total"', response.content)
        self.assertIn(b'id="chart-projected-total"', response.content)
        self.assertIn(b'id="manual-expense-form"', response.content)
        self.assertIn("Mês inicial".encode(), response.content)
        self.assertNotIn(b'id="card-forecast-form"', response.content)
        self.assertIn(b'id="manual-expense-type"', response.content)
        self.assertIn(b'id="manual-expense-cancel"', response.content)
        self.assertIn(b'<option value="credito">', response.content)
        self.assertIn(b'id="include-actual"', response.content)
        self.assertIn(b'id="include-projected"', response.content)
        self.assertNotIn(
            b'id="include-projected" type="checkbox" checked',
            response.content,
        )
        self.assertIn(b'id="breakdown-kind"', response.content)
        self.assertIn(b'id="manual-expense-recurrence-mode"', response.content)
        self.assertIn(b'id="manual-expense-recurrence-end"', response.content)
        self.assertIn(b'id="monthly-balance-form"', response.content)
        self.assertIn(b'id="balance-expense-scope"', response.content)
        self.assertIn("Somente cartão".encode(), response.content)
        self.assertIn("Cartão + outros lançamentos".encode(), response.content)
        self.assertIn("Mês fechado".encode(), response.content)
        self.assertIn(b'id="include-monthly-balance"', response.content)
        self.assertIn(b'id="include-accumulated-balance"', response.content)
        self.assertNotIn(b'id="include-monthly-balance" type="checkbox" checked', response.content)
        self.assertNotIn(b'id="include-accumulated-balance" type="checkbox" checked', response.content)
        self.assertIn(b'id="balance-history-chart"', response.content)
        self.assertIn(b'id="compound-interest-enabled"', response.content)
        self.assertIn(b'id="compound-interest-rate"', response.content)
        self.assertIn(b'id="compound-interest-summary"', response.content)
        self.assertNotIn(b'id="current-month-pie"', response.content)
        self.assertIn(b'id="breakdown-month"', response.content)
        self.assertIn(b'id="breakdown-source"', response.content)
        self.assertIn("Outros meios".encode(), response.content)
        self.assertIn(b'id="breakdown-category"', response.content)
        self.assertIn(b'id="category-breakdown-chart"', response.content)
        self.assertIn(b'id="breakdown-entry-list"', response.content)
        self.assertIn(b'id="show-category-create"', response.content)
        self.assertIn(b'id="transaction-filters"', response.content)
        self.assertIn(b'data-sort="merchant"', response.content)
        self.assertIn("Parcelamento".encode(), response.content)
        self.assertIn("Recorrência".encode(), response.content)
        self.assertIn(b"/static/vendor/chart.umd.min.js", response.content)
        self.assertIn(b'id="assistant-launcher"', response.content)
        self.assertIn(b'id="assistant-panel"', response.content)
        self.assertIn(b'id="assistant-messages"', response.content)
        self.assertIn(b'id="assistant-form"', response.content)
        self.assertIn(b"/static/assistant.css", response.content)
        self.assertIn(b"/static/assistant.js", response.content)
        self.assertNotIn(b"cdn.jsdelivr", response.content)

        javascript = self.client.get("/static/app.js")
        self.assertEqual(javascript.status_code, 200)
        self.assertIn(b"manualExpenseMonth.value = nextMonth", javascript.content)
        self.assertIn(b"balanceMonth.max = data.reference_month", javascript.content)
        self.assertIn(b"Sai do guardado", javascript.content)
        self.assertIn(b'label: "Saldo mensal"', javascript.content)
        self.assertIn(b'label: "Saldo acumulado"', javascript.content)
        self.assertIn(b"renderBalanceHistory(data)", javascript.content)
        self.assertIn(b'label: "Total guardado"', javascript.content)
        self.assertIn(b"simulatedBalance += interest + Number(item.total)", javascript.content)
        self.assertIn(b"isCompoundInterest: true", javascript.content)
        self.assertIn(b'include_expense_income: "true"', javascript.content)
        self.assertIn(b"loadMonthlyBreakdown", javascript.content)
        self.assertIn(b"selectBreakdownCategory", javascript.content)
        self.assertIn(b'entry.source_group === breakdownSource.value', javascript.content)
        self.assertIn(b"?include_manual=${includeManual}", javascript.content)
        self.assertIn(b'balanceExpenseScope.value === "card_only"', javascript.content)

        assistant_javascript = self.client.get("/static/assistant.js")
        self.assertEqual(assistant_javascript.status_code, 200)
        self.assertIn(b'/api/assistant/chat', assistant_javascript.content)
        self.assertIn(b"pending_approval", assistant_javascript.content)

        assistant_styles = self.client.get("/static/assistant.css")
        self.assertEqual(assistant_styles.status_code, 200)
        self.assertIn(b".assistant-panel", assistant_styles.content)
        self.assertIn(b"@media(max-width:560px)", assistant_styles.content)

    def test_liveness_e_logs_locais(self):
        self.assertEqual(self.client.get("/health/live").json(), {"status": "ok"})
        response = self.client.get("/api/system/logs?limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertIn("events", response.json())

    def test_chat_conecta_hud_ao_assistente_e_confirma_operacao(self):
        thread_id = "7644e790-652d-4aa7-8b27-c52bb6bb86ac"
        chat = self.client.post("/api/assistant/chat", json={"thread_id": thread_id, "message": "Adicione uma despesa"}, headers={"X-CSRF-Token": self.csrf})

        self.assertEqual(chat.status_code, 200)
        self.assertEqual(chat.json()["answer"], "Resposta financeira de teste.")
        self.assertEqual(chat.json()["pending_approval"]["id"], "interrupt-1")
        self.assertEqual(self.assistant.messages, [(thread_id, "Adicione uma despesa")])

        decision = self.client.post("/api/assistant/chat/decision", json={"thread_id": thread_id, "interrupt_id": "interrupt-1", "decision": "approve"}, headers={"X-CSRF-Token": self.csrf})

        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.json()["answer"], "Operacao confirmada.")
        self.assertEqual(self.assistant.decisions, [(thread_id, "interrupt-1", "approve")])

    def test_chat_exige_csrf_e_identificador_de_thread_valido(self):
        missing_csrf = self.client.post("/api/assistant/chat", json={"thread_id": "7644e790-652d-4aa7-8b27-c52bb6bb86ac", "message": "Consulte meus gastos"})
        invalid_thread = self.client.post("/api/assistant/chat", json={"thread_id": "invalido", "message": "Consulte meus gastos"}, headers={"X-CSRF-Token": self.csrf})

        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(invalid_thread.status_code, 422)

    def test_registra_pdf_ficticio(self):
        request_id = "7644e790-652d-4aa7-8b27-c52bb6bb86ac"
        response = self.client.post(
            "/api/invoices",
            data={"name": "Itau pessoal", "reference_date": "2026-08-01"},
            files={
                "invoice": (
                    "fatura-ficticia.pdf",
                    io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
                    "application/pdf",
                )
            },
            headers={"X-CSRF-Token": self.csrf, "X-Request-ID": request_id},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["X-Request-ID"], request_id)
        self.assertEqual(len(self.app.state.store.list_all()), 1)
        self.assertEqual(self.app.state.store.list_all()[0]["name"], "Itau pessoal")
        events = self.app.state.container.audit.recent(20)
        register_event = next(item for item in events if item["event"] == "invoice.register")
        self.assertEqual(register_event["request_id"], request_id)

    def test_recusa_post_sem_csrf(self):
        response = self.client.post("/api/invoices")
        self.assertEqual(response.status_code, 403)

    def test_lista_e_confirma_categoria(self):
        categories = self.client.get("/api/categories")
        self.assertEqual(categories.status_code, 200)
        self.assertEqual(categories.json()["items"][0]["slug"], "transporte")

        transactions = self.client.get("/api/transactions")
        self.assertEqual(transactions.status_code, 200)
        self.assertEqual(transactions.json()["total"], 1)

        response = self.client.put(
            "/api/transactions/10/category",
            json={
                "category_slug": "transporte",
                "scope": "merchant",
                "merchant_name": "Transporte ficticio",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.categorization.categorizations,
            [(10, "transporte", "merchant", "Transporte ficticio")],
        )

    def test_repassa_filtros_de_transacao_ao_repositorio(self):
        response = self.client.get(
            "/api/transactions?q=Corrida&category=transporte&status=pending"
            "&sort=amount&direction=asc"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.categorization.last_transaction_filters,
            ("Corrida", "transporte", "pending", "amount", "asc"),
        )

    def test_cria_categoria_com_slug_normalizado(self):
        response = self.client.post(
            "/api/categories",
            json={"name": "Posto de gasolina"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["item"]["slug"], "posto_de_gasolina")
        self.assertEqual(
            self.categorization.created_categories,
            [("posto_de_gasolina", "Posto de gasolina")],
        )

    def test_dashboard_serializa_decimal(self):
        response = self.client.get("/api/analytics/monthly?months=12")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reference_month"], "2026-07")
        self.assertEqual(response.json()["series"][0]["total"], "42.50")
        self.assertEqual(response.json()["series"][0]["kind"], "actual")
        self.assertEqual(response.json()["series"][1]["kind"], "projected")
        self.assertFalse(response.json()["include_expense_income"])
        self.assertEqual(response.json()["expense_income_projection"], [])

    def test_dashboard_projeta_rendimento_menos_gastos(self):
        response = self.client.get(
            "/api/analytics/monthly?months=12&include_card=true"
            "&include_manual=false&include_expense_income=true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.categorization.last_monthly_filters,
            (12, True, False, True, True, True),
        )
        self.assertEqual(
            response.json()["expense_income_projection"],
            [
                {
                    "month": "2026-07",
                    "expenses": "42.50",
                    "income": "100.00",
                    "total": "57.50",
                    "saved_balance": "1057.50",
                },
                {
                    "month": "2026-08",
                    "expenses": "42.50",
                    "income": "100.00",
                    "total": "57.50",
                    "saved_balance": "1115.00",
                },
            ],
        )

    def test_detalha_categorias_e_lancamentos_do_mes(self):
        response = self.client.get("/api/analytics/monthly/2026-07/breakdown")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], "42.50")
        self.assertEqual(
            response.json()["categories"],
            [
                {
                    "category": "transporte",
                    "category_name": "Transporte",
                    "total": "42.50",
                    "count": 1,
                }
            ],
        )
        self.assertEqual(
            response.json()["entries"][0]["description"],
            "Corrida fictícia",
        )
        self.assertEqual(response.json()["entries"][0]["source_group"], "card")

        before_closing = self.client.get(
            "/api/analytics/monthly/2026-06/breakdown"
        )
        self.assertEqual(before_closing.status_code, 400)

    def test_fluxo_de_caixa_manual_e_resultado_mensal(self):
        created = self.client.post(
            "/api/cash-flow/expenses",
            json={
                "month": "2026-07",
                "description": "Faculdade fictícia",
                "amount": "500.00",
                "category_slug": "educacao",
                "payment_method": "pix",
                "expense_type": "actual",
                "recurrence_mode": "unlimited",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["item"]["amount"], "500.00")
        self.assertEqual(created.json()["item"]["expense_type"], "actual")
        self.assertEqual(created.json()["item"]["recurrence_mode"], "unlimited")

        recurrence = self.client.put(
            "/api/cash-flow/expenses/1/recurrence",
            json={"mode": "until", "end_month": "2026-12"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(recurrence.status_code, 200)
        self.assertEqual(self.cash_flow.expenses[0]["recurrence_mode"], "until")
        self.assertEqual(
            self.cash_flow.expenses[0]["recurrence_end_month"], "2026-12"
        )

        invalid_recurrence = self.client.put(
            "/api/cash-flow/expenses/1/recurrence",
            json={"mode": "until", "end_month": "2026-06"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(invalid_recurrence.status_code, 400)

        saved = self.client.put(
            "/api/cash-flow/monthly/2026-07",
            json={"income": "5000.00", "saved_base": "1000.00"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["item"]["result"], "2500.00")

        card_only = self.client.get(
            "/api/cash-flow/monthly/2026-07?include_manual=false"
        )
        self.assertEqual(card_only.status_code, 200)
        self.assertFalse(card_only.json()["include_manual"])
        self.assertEqual(card_only.json()["total_expenses"], "2000.00")
        self.assertEqual(card_only.json()["result"], "3000.00")

        applied = self.client.post(
            "/api/cash-flow/monthly/2026-07/apply-result",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["item"]["saved_total"], "3500.00")

    def test_gasto_previsto_entra_na_simulacao_do_proximo_mes(self):
        created = self.client.post(
            "/api/cash-flow/card-forecasts",
            json={
                "month": "2026-08",
                "description": "Compra futura fictícia",
                "amount": "125.90",
                "category_slug": "outros",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["item"]["amount"], "125.90")

        listed = self.client.get("/api/cash-flow/card-forecasts")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["items"]), 1)

        invalid_month = self.client.post(
            "/api/cash-flow/card-forecasts",
            json={
                "month": "2026-07",
                "description": "Fora da projeção",
                "amount": "10.00",
                "category_slug": "outros",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(invalid_month.status_code, 400)

        removed = self.client.delete(
            "/api/cash-flow/card-forecasts/1",
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.cash_flow.forecasts, [])

    def test_lancamento_unificado_aceita_credito_previsto_e_recorrencia(self):
        created = self.client.post(
            "/api/cash-flow/expenses",
            json={
                "month": "2026-08",
                "description": "Assinatura futura fictícia",
                "amount": "89.90",
                "category_slug": "outros",
                "payment_method": "credito",
                "expense_type": "planned",
                "recurrence_mode": "until",
                "recurrence_end_month": "2026-12",
            },
            headers={"X-CSRF-Token": self.csrf},
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["item"]["payment_method"], "credito")
        self.assertEqual(created.json()["item"]["expense_type"], "planned")
        self.assertEqual(created.json()["item"]["recurrence_mode"], "until")
        self.assertEqual(
            created.json()["item"]["recurrence_end_month"], "2026-12"
        )

        future_actual = self.client.post(
            "/api/cash-flow/expenses",
            json={
                "month": "2026-08",
                "description": "Real fora do fechamento",
                "amount": "10.00",
                "category_slug": "outros",
                "payment_method": "pix",
                "expense_type": "actual",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(future_actual.status_code, 201)
        self.assertEqual(future_actual.json()["item"]["expense_type"], "actual")

        closed_planned = self.client.post(
            "/api/cash-flow/expenses",
            json={
                "month": "2026-07",
                "description": "Previsão em mês fechado",
                "amount": "10.00",
                "category_slug": "outros",
                "payment_method": "pix",
                "expense_type": "planned",
            },
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(closed_planned.status_code, 201)
        self.assertEqual(closed_planned.json()["item"]["expense_type"], "planned")

    def test_edita_todos_os_dados_do_lancamento(self):
        created = self.cash_flow.create_expense(
            "2026-08",
            "Faculdade",
            Decimal("500.00"),
            "educacao",
            "pix",
            "actual",
            "none",
            None,
        )

        response = self.client.put(
            f"/api/cash-flow/expenses/{created['id']}",
            json={
                "month": "2026-09",
                "description": "Faculdade simulada",
                "amount": "550.00",
                "category_slug": "outros",
                "payment_method": "credito",
                "expense_type": "planned",
                "recurrence_mode": "until",
                "recurrence_end_month": "2026-12",
            },
            headers={"X-CSRF-Token": self.csrf},
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["item"]
        self.assertEqual(item["month"], "2026-09")
        self.assertEqual(item["description"], "Faculdade simulada")
        self.assertEqual(item["amount"], "550.00")
        self.assertEqual(item["payment_method"], "credito")
        self.assertEqual(item["expense_type"], "planned")
        self.assertEqual(item["recurrence_mode"], "until")
        self.assertEqual(item["recurrence_end_month"], "2026-12")

    def test_uniao_de_alias(self):
        response = self.client.post(
            "/api/aliases/est_111111111111/merge",
            json={"merchant_id": "est_222222222222"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.categorization.merges,
            [("est_111111111111", "est_222222222222")],
        )

    def test_define_recorrencia_com_prazo(self):
        response = self.client.put(
            "/api/transactions/10/recurrence",
            json={"mode": "until", "end_month": "2027-03"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.categorization.recurrences,
            [(10, "until", "2027-03")],
        )

    def test_categorizacao_exige_csrf(self):
        response = self.client.put(
            "/api/transactions/10/category",
            json={"category_slug": "transporte", "scope": "transaction"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
