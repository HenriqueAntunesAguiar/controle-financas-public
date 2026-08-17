const token = document.querySelector('meta[name="csrf-token"]').content;
const toast = document.querySelector("#toast");
const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#invoice-file");
const fileLabel = document.querySelector("#file-label");
const dropZone = document.querySelector("#drop-zone");
const passwordDialog = document.querySelector("#password-dialog");
const processForm = document.querySelector("#process-form");
const password = document.querySelector("#pdf-password");
const categoryDialog = document.querySelector("#category-dialog");
const categoryForm = document.querySelector("#category-form");
const categorySelect = document.querySelector("#category-select");
const showCategoryCreate = document.querySelector("#show-category-create");
const categoryCreatePanel = document.querySelector("#category-create-panel");
const newCategoryName = document.querySelector("#new-category-name");
const createCategoryButton = document.querySelector("#create-category");
const cancelCategoryCreate = document.querySelector("#cancel-category-create");
const merchantName = document.querySelector("#merchant-name");
const merchantMerge = document.querySelector("#merchant-merge");
const recurrenceMode = document.querySelector("#recurrence-mode");
const recurrenceEndField = document.querySelector("#recurrence-end-field");
const recurrenceEndMonth = document.querySelector("#recurrence-end-month");
const categoryDescription = document.querySelector("#category-description");
const transactionList = document.querySelector("#transaction-list");
const transactionCount = document.querySelector("#transaction-count");
const refreshTransactions = document.querySelector("#refresh-transactions");
const transactionFilters = document.querySelector("#transaction-filters");
const transactionSearch = document.querySelector("#transaction-search");
const transactionCategoryFilter = document.querySelector("#transaction-category-filter");
const transactionStatusFilter = document.querySelector("#transaction-status-filter");
const clearTransactionFilters = document.querySelector("#clear-transaction-filters");
const dashboardMonths = document.querySelector("#dashboard-months");
const includeCard = document.querySelector("#include-card");
const includeManual = document.querySelector("#include-manual");
const includeActual = document.querySelector("#include-actual");
const includeProjected = document.querySelector("#include-projected");
const includeMonthlyBalance = document.querySelector("#include-monthly-balance");
const includeAccumulatedBalance = document.querySelector("#include-accumulated-balance");
const compoundInterestEnabled = document.querySelector("#compound-interest-enabled");
const compoundInterestRate = document.querySelector("#compound-interest-rate");
const compoundInterestSummary = document.querySelector("#compound-interest-summary");
const breakdownMonth = document.querySelector("#breakdown-month");
const breakdownSource = document.querySelector("#breakdown-source");
const breakdownKind = document.querySelector("#breakdown-kind");
const breakdownCategory = document.querySelector("#breakdown-category");
const breakdownEntryList = document.querySelector("#breakdown-entry-list");
const manualExpenseForm = document.querySelector("#manual-expense-form");
const manualExpenseMonth = document.querySelector("#manual-expense-month");
const manualExpenseDescription = document.querySelector("#manual-expense-description");
const manualExpenseAmount = document.querySelector("#manual-expense-amount");
const manualExpenseCategory = document.querySelector("#manual-expense-category");
const manualExpenseType = document.querySelector("#manual-expense-type");
const manualExpensePayment = document.querySelector("#manual-expense-payment");
const manualExpenseRecurrenceMode = document.querySelector("#manual-expense-recurrence-mode");
const manualExpenseRecurrenceEndField = document.querySelector("#manual-expense-recurrence-end-field");
const manualExpenseRecurrenceEnd = document.querySelector("#manual-expense-recurrence-end");
const manualExpenseList = document.querySelector("#manual-expense-list");
const refreshManualExpenses = document.querySelector("#refresh-manual-expenses");
const manualExpenseFormTitle = document.querySelector("#manual-expense-form-title");
const manualExpenseSubmit = document.querySelector("#manual-expense-submit");
const manualExpenseCancel = document.querySelector("#manual-expense-cancel");
const monthlyBalanceForm = document.querySelector("#monthly-balance-form");
const balanceMonth = document.querySelector("#balance-month");
const balanceExpenseScope = document.querySelector("#balance-expense-scope");
const monthlyIncome = document.querySelector("#monthly-income");
const savedBase = document.querySelector("#saved-base");
const applyMonthResult = document.querySelector("#apply-month-result");
let currentInvoiceId = null;
let currentTransaction = null;
let categories = [];
let monthlyChart = null;
let balanceHistoryChart = null;
let categoryBreakdownChart = null;
let monthlyBreakdownData = null;
let visibleBreakdownData = null;
let latestDashboardData = null;
let transactionSort = {field: "date", direction: "desc"};
let editingExpenseId = null;

function notify(message, error = false) {
  toast.textContent = message;
  toast.className = error ? "show error" : "show";
  setTimeout(() => toast.className = "", 4000);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {"X-CSRF-Token": token, ...(options.headers || {})},
  });
  const data = await response.json().catch(() => ({error: "Resposta local inválida."}));
  if (!response.ok) throw new Error(data.error || "Operação não concluída.");
  return data;
}

function textElement(tag, className, value) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = value;
  return element;
}

function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", {style: "currency", currency: "BRL"})
    .format(Number(value));
}

function formatCompactCurrency(value) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number(value));
}

function formatPercentage(value, total) {
  if (!Number(total)) return "0%";
  return new Intl.NumberFormat("pt-BR", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(Number(value) / Number(total));
}

fileInput.addEventListener("change", () => {
  fileLabel.textContent = fileInput.files[0]?.name || "Solte o PDF aqui";
  dropZone.classList.toggle("selected", fileInput.files.length > 0);
});

["dragover", "dragenter"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach(name => dropZone.addEventListener(name, event => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", event => {
  fileInput.files = event.dataTransfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

uploadForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = uploadForm.querySelector("button");
  button.disabled = true;
  button.textContent = "Registrando…";
  try {
    const data = await api("/api/invoices", {method: "POST", body: new FormData(uploadForm)});
    notify(data.message);
    setTimeout(() => location.reload(), 500);
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
    button.textContent = "Registrar localmente →";
  }
});

document.querySelectorAll(".process").forEach(button => button.addEventListener("click", () => {
  currentInvoiceId = button.dataset.id;
  password.value = "";
  passwordDialog.showModal();
}));
document.querySelector("#password-dialog .close").addEventListener("click", () => passwordDialog.close());
processForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = processForm.querySelector(".primary");
  button.disabled = true;
  button.textContent = "Processando…";
  try {
    const data = await api(`/api/invoices/${currentInvoiceId}/process`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({senha: password.value}),
    });
    password.value = "";
    passwordDialog.close();
    notify(data.message);
    setTimeout(() => location.reload(), 600);
  } catch (error) {
    password.value = "";
    notify(error.message, true);
    button.disabled = false;
    button.textContent = "Criar nova versão";
  }
});

document.querySelectorAll(".import").forEach(button => button.addEventListener("click", async () => {
  button.disabled = true;
  const old = button.textContent;
  button.textContent = "Enviando…";
  try {
    const data = await api(`/api/invoices/${button.dataset.id}/import`, {method: "POST"});
    notify(data.message);
    setTimeout(() => location.reload(), 600);
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
    button.textContent = old;
  }
}));

document.querySelectorAll(".approve").forEach(button => button.addEventListener("click", async () => {
  button.disabled = true;
  const old = button.textContent;
  button.textContent = "Aprovando…";
  try {
    const data = await api(`/api/invoices/${button.dataset.id}/approve`, {method: "POST"});
    notify(data.message);
    setTimeout(() => location.reload(), 600);
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
    button.textContent = old;
  }
}));

function categoryOptions(selected) {
  categorySelect.replaceChildren();
  categories.forEach(category => {
    const option = document.createElement("option");
    option.value = category.slug;
    option.textContent = category.nome;
    option.selected = category.slug === selected;
    categorySelect.append(option);
  });
}

function categoryFilterOptions() {
  const selected = transactionCategoryFilter.value;
  transactionCategoryFilter.replaceChildren(new Option("Todas as categorias", ""));
  categories.forEach(category => {
    transactionCategoryFilter.append(new Option(category.nome, category.slug));
  });
  transactionCategoryFilter.value = selected;
  const manualSelected = manualExpenseCategory.value;
  manualExpenseCategory.replaceChildren();
  categories.forEach(category => {
    manualExpenseCategory.append(new Option(category.nome, category.slug));
  });
  if (manualSelected) manualExpenseCategory.value = manualSelected;
}

async function openCategoryDialog(transaction) {
  currentTransaction = transaction;
  categoryDescription.textContent = `${transaction.descricao} · ${formatCurrency(transaction.valor)}`;
  merchantName.value = transaction.estabelecimento_nome;
  categoryOptions(transaction.categoria_efetiva);
  categoryCreatePanel.hidden = true;
  showCategoryCreate.hidden = false;
  newCategoryName.value = "";
  recurrenceMode.value = transaction.recurrence_mode || "none";
  recurrenceEndMonth.value = transaction.recurrence_end_month || "";
  updateRecurrenceFields();
  merchantMerge.replaceChildren(new Option("Não unir aliases", ""));
  try {
    const data = await api("/api/merchants?limit=50");
    data.items.forEach(merchant => {
      if (merchant.id !== transaction.estabelecimento_id) {
        merchantMerge.append(new Option(merchant.nome_canonico, merchant.id));
      }
    });
  } catch (error) {
    notify(error.message, true);
  }
  categoryDialog.showModal();
}

function updateRecurrenceFields() {
  const hasDeadline = recurrenceMode.value === "until";
  recurrenceEndField.hidden = !hasDeadline;
  recurrenceEndMonth.required = hasDeadline;
  if (!hasDeadline) recurrenceEndMonth.value = "";
}

recurrenceMode.addEventListener("change", updateRecurrenceFields);

showCategoryCreate.addEventListener("click", () => {
  showCategoryCreate.hidden = true;
  categoryCreatePanel.hidden = false;
  newCategoryName.focus();
});

cancelCategoryCreate.addEventListener("click", () => {
  categoryCreatePanel.hidden = true;
  showCategoryCreate.hidden = false;
  newCategoryName.value = "";
});

createCategoryButton.addEventListener("click", async () => {
  const name = newCategoryName.value.trim();
  if (name.length < 2) {
    notify("Informe um nome para a categoria.", true);
    return;
  }
  createCategoryButton.disabled = true;
  try {
    const response = await api("/api/categories", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name}),
    });
    categories = categories.filter(category => category.slug !== response.item.slug);
    categories.push(response.item);
    categories.sort((left, right) => left.nome.localeCompare(right.nome, "pt-BR"));
    categoryOptions(response.item.slug);
    categoryFilterOptions();
    categoryCreatePanel.hidden = true;
    showCategoryCreate.hidden = false;
    newCategoryName.value = "";
    notify(response.message);
  } catch (error) {
    notify(error.message, true);
  } finally {
    createCategoryButton.disabled = false;
  }
});

function renderTransactions(data) {
  transactionList.replaceChildren();
  if (!data.items.length) {
    const row = document.createElement("tr");
    const cell = textElement("td", "loading", "Nenhuma transação importada.");
    cell.colSpan = 8;
    row.append(cell);
    transactionList.append(row);
  }
  data.items.forEach(transaction => {
    const row = document.createElement("tr");
    const merchant = document.createElement("td");
    merchant.className = "merchant-cell";
    merchant.append(
      textElement("strong", "", transaction.estabelecimento_nome),
      textElement("small", "", transaction.descricao),
    );
    const category = document.createElement("td");
    category.append(textElement("span", "category-pill", transaction.categoria_efetiva));
    if (transaction.categoria_sugerida) {
      category.append(textElement(
        "small",
        "suggestion",
        `Sugestão: ${transaction.categoria_sugerida} (${Math.round(transaction.sugestao_confianca * 100)}%)`,
      ));
    }
    const source = document.createElement("td");
    source.append(textElement("span", "source-pill", transaction.categoria_origem));
    const installment = document.createElement("td");
    const isInstallment = Number(transaction.parcela_atual) > 0
      && Number(transaction.total_parcelas) > 1;
    installment.append(textElement(
      "span",
      isInstallment ? "installment-pill active" : "installment-pill",
      isInstallment
        ? `Parcela ${transaction.parcela_atual} de ${transaction.total_parcelas}`
        : "À vista",
    ));
    const recurrence = document.createElement("td");
    let recurrenceLabel = "Não recorrente";
    if (transaction.recurrence_mode === "unlimited") {
      recurrenceLabel = "Sem prazo";
    } else if (transaction.recurrence_mode === "until") {
      const [year, month] = transaction.recurrence_end_month.split("-");
      recurrenceLabel = `Até ${month}/${year}`;
    }
    recurrence.append(textElement(
      "span",
      transaction.recurrence_mode ? "recurrence-pill active" : "recurrence-pill",
      recurrenceLabel,
    ));
    const action = document.createElement("td");
    const button = textElement("button", "secondary", "Categorizar");
    button.type = "button";
    button.addEventListener("click", () => openCategoryDialog(transaction));
    action.append(button);
    row.append(
      textElement("td", "", transaction.data_transacao || "—"),
      merchant,
      textElement("td", "", formatCurrency(transaction.valor)),
      installment,
      recurrence,
      category,
      source,
      action,
    );
    transactionList.append(row);
  });
  transactionCount.textContent = `${data.total} transações nas versões mais recentes das faturas.`;
}

async function loadTransactions() {
  refreshTransactions.disabled = true;
  try {
    const query = new URLSearchParams({
      limit: "100",
      q: transactionSearch.value.trim(),
      category: transactionCategoryFilter.value,
      status: transactionStatusFilter.value,
      sort: transactionSort.field,
      direction: transactionSort.direction,
    });
    renderTransactions(await api(`/api/transactions?${query}`));
  } catch (error) {
    transactionList.replaceChildren();
    const row = document.createElement("tr");
    const cell = textElement("td", "diagnostic-error", error.message);
    cell.colSpan = 8;
    row.append(cell);
    transactionList.append(row);
  } finally {
    refreshTransactions.disabled = false;
  }
}

function updateSortIndicators() {
  document.querySelectorAll(".transaction-table th[data-sort]").forEach(header => {
    const active = header.dataset.sort === transactionSort.field;
    header.setAttribute(
      "aria-sort",
      active ? (transactionSort.direction === "asc" ? "ascending" : "descending") : "none",
    );
    header.querySelector(".sort-indicator").textContent = active
      ? (transactionSort.direction === "asc" ? "↑" : "↓")
      : "";
  });
}

document.querySelectorAll(".transaction-table th[data-sort] .sort-button").forEach(button => {
  button.addEventListener("click", () => {
    const field = button.closest("th").dataset.sort;
    transactionSort = {
      field,
      direction: transactionSort.field === field && transactionSort.direction === "asc"
        ? "desc"
        : "asc",
    };
    updateSortIndicators();
    loadTransactions();
  });
});

transactionFilters.addEventListener("submit", event => {
  event.preventDefault();
  loadTransactions();
});

clearTransactionFilters.addEventListener("click", () => {
  transactionFilters.reset();
  loadTransactions();
});

document.querySelector(".category-close").addEventListener("click", () => categoryDialog.close());
categoryForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = categoryForm.querySelector(".primary");
  button.disabled = true;
  button.textContent = "Confirmando…";
  try {
    let scope = categoryForm.querySelector('input[name="category-scope"]:checked').value;
    if (merchantMerge.value) {
      await api(`/api/aliases/${currentTransaction.alias_hash}/merge`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({merchant_id: merchantMerge.value}),
      });
      scope = "merchant";
    }
    const data = await api(`/api/transactions/${currentTransaction.id}/category`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        category_slug: categorySelect.value,
        scope,
        merchant_name: merchantName.value,
      }),
    });
    const recurrence = await api(`/api/transactions/${currentTransaction.id}/recurrence`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        mode: recurrenceMode.value,
        end_month: recurrenceMode.value === "until" ? recurrenceEndMonth.value : null,
      }),
    });
    categoryDialog.close();
    notify(`${data.message} ${recurrence.message}`);
    await Promise.all([loadTransactions(), loadDashboard()]);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Confirmar categoria";
  }
});

const chartPalette = ["#286348", "#c67955", "#d9a441", "#4973a6", "#8b5e83", "#6f8e5d", "#b84d55", "#6d695f"];

function colorWithAlpha(hex, alpha) {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${value >> 16}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function renderBalanceHistory(data) {
  const canvas = document.querySelector("#balance-history-chart");
  const empty = document.querySelector("#balance-history-empty");
  const rows = data.expense_income_projection || [];
  canvas.hidden = rows.length === 0;
  empty.hidden = rows.length > 0;
  if (balanceHistoryChart) balanceHistoryChart.destroy();
  if (!rows.length || typeof Chart === "undefined") {
    compoundInterestSummary.hidden = true;
    return;
  }
  const labels = rows.map(item => new Date(`${item.month}-01T00:00:00Z`).toLocaleDateString(
    "pt-BR", {month: "short", year: "2-digit", timeZone: "UTC"},
  ));
  const simulateInterest = compoundInterestEnabled.checked;
  const monthlyRate = Math.max(0, Number(compoundInterestRate.value) || 0);
  let simulatedBalance = Number(data.saved_base) || 0;
  let accumulatedInterest = 0;
  const compoundProjection = rows.map(item => {
    const interest = simulatedBalance * (monthlyRate / 100);
    accumulatedInterest += interest;
    simulatedBalance += interest + Number(item.total);
    return {balance: simulatedBalance, interest};
  });
  const datasets = [
    {
      label: "Total guardado",
      data: rows.map(item => Number(item.saved_balance)),
      borderColor: "#9b6b21",
      backgroundColor: "rgba(217, 164, 65, .16)",
      borderWidth: 3,
      pointRadius: 3,
      pointHoverRadius: 5,
      tension: 0.25,
      fill: true,
      order: 1,
    },
    {
      label: "Rendimento",
      data: rows.map(item => Number(item.income)),
      borderColor: "#2e7659",
      backgroundColor: "#2e7659",
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: 2,
      tension: 0.2,
      order: 3,
    },
    {
      label: "Gastos",
      data: rows.map(item => Number(item.expenses)),
      borderColor: "#a54131",
      backgroundColor: "#a54131",
      borderWidth: 2,
      borderDash: [3, 4],
      pointRadius: 2,
      tension: 0.2,
      order: 4,
    },
  ];
  if (simulateInterest) {
    datasets.splice(1, 0, {
      label: `Com juros (${monthlyRate.toLocaleString("pt-BR")}% a.m.)`,
      data: compoundProjection.map(item => item.balance),
      monthlyInterest: compoundProjection.map(item => item.interest),
      isCompoundInterest: true,
      borderColor: "#4973a6",
      backgroundColor: "#4973a6",
      borderWidth: 3,
      pointRadius: 3,
      pointHoverRadius: 5,
      tension: 0.25,
      fill: false,
      order: 2,
    });
  }
  compoundInterestSummary.hidden = !simulateInterest;
  if (simulateInterest) {
    compoundInterestSummary.textContent =
      `Saldo final simulado: ${formatCurrency(simulatedBalance)} · juros acumulados: ${formatCurrency(accumulatedInterest)}. O saldo anterior rende antes da entrada do resultado mensal.`;
  }
  balanceHistoryChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {boxWidth: 10, usePointStyle: true, padding: 12, font: {size: 10}},
        },
        tooltip: {
          padding: 12,
          callbacks: {
            label: context => {
              if (context.dataset.isCompoundInterest) {
                return [
                  `${context.dataset.label}: ${formatCurrency(context.raw)}`,
                  `Juros do mês: ${formatCurrency(context.dataset.monthlyInterest[context.dataIndex])}`,
                ];
              }
              return `${context.dataset.label}: ${formatCurrency(context.raw)}`;
            },
          },
        },
      },
      scales: {
        x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 6}},
        y: {beginAtZero: true, ticks: {callback: value => formatCompactCurrency(value)}},
      },
    },
  });
}

function syncBreakdownMonths(data) {
  const availableMonths = (data.expense_income_projection || []).map(item => item.month);
  const previousMonth = breakdownMonth.value;
  breakdownMonth.replaceChildren();
  availableMonths.forEach(month => {
    const label = new Date(`${month}-01T00:00:00Z`).toLocaleDateString(
      "pt-BR", {month: "long", year: "numeric", timeZone: "UTC"},
    );
    breakdownMonth.add(new Option(label, month));
  });
  breakdownMonth.disabled = availableMonths.length === 0;
  if (availableMonths.includes(previousMonth)) {
    breakdownMonth.value = previousMonth;
  } else if (data.reference_month && availableMonths.includes(data.reference_month)) {
    breakdownMonth.value = data.reference_month;
  }
}

function selectBreakdownCategory(categorySlug) {
  if (!visibleBreakdownData) return;
  const category = visibleBreakdownData.categories.find(
    item => item.category === categorySlug,
  );
  if (!category) return;
  breakdownCategory.value = categorySlug;
  document.querySelector("#breakdown-category-title").textContent = category.category_name;
  document.querySelector("#breakdown-category-total").textContent = formatCurrency(category.total);
  const entries = visibleBreakdownData.entries.filter(
    entry => entry.category === categorySlug,
  );
  document.querySelector("#breakdown-entry-count").textContent =
    `${entries.length} ${entries.length === 1 ? "lançamento" : "lançamentos"}`;
  breakdownEntryList.replaceChildren();
  entries.forEach(entry => {
    const item = document.createElement("article");
    item.className = "breakdown-entry-item";
    const identity = document.createElement("div");
    const status = entry.kind === "projected" ? "previsto" : "real";
    const source = textElement(
      "small",
      entry.kind === "projected" ? "projected" : "",
      `${entry.source_label} · ${status}`,
    );
    identity.append(textElement("strong", "", entry.description), source);
    item.append(identity, textElement("b", "", formatCurrency(entry.amount)));
    breakdownEntryList.append(item);
  });
  if (categoryBreakdownChart) {
    const index = visibleBreakdownData.categories.findIndex(
      item => item.category === categorySlug,
    );
    categoryBreakdownChart.setActiveElements([{datasetIndex: 0, index}]);
    categoryBreakdownChart.update();
  }
}

function renderMonthlyBreakdown(data) {
  monthlyBreakdownData = data;
  renderBreakdownSource();
}

function renderBreakdownSource() {
  if (!monthlyBreakdownData) return;
  const entries = monthlyBreakdownData.entries.filter(entry => (
    (breakdownSource.value === "all" || entry.source_group === breakdownSource.value)
    && (breakdownKind.value === "all" || entry.kind === breakdownKind.value)
  ));
  const grouped = new Map();
  entries.forEach(entry => {
    const current = grouped.get(entry.category) || {
      category: entry.category,
      category_name: entry.category_name,
      total: 0,
      count: 0,
    };
    current.total += Number(entry.amount);
    current.count += 1;
    grouped.set(entry.category, current);
  });
  const categories = [...grouped.values()].sort((left, right) =>
    right.total - left.total || left.category_name.localeCompare(right.category_name, "pt-BR")
  );
  visibleBreakdownData = {...monthlyBreakdownData, entries, categories};
  renderBreakdownView(visibleBreakdownData);
}

function renderBreakdownView(data) {
  const categories = data.categories || [];
  const canvas = document.querySelector("#category-breakdown-chart");
  const empty = document.querySelector("#category-breakdown-empty");
  const previousCategory = breakdownCategory.value;
  breakdownCategory.replaceChildren();
  categories.forEach(category => {
    breakdownCategory.add(new Option(category.category_name, category.category));
  });
  breakdownCategory.disabled = categories.length === 0;
  canvas.hidden = categories.length === 0;
  empty.hidden = categories.length > 0;
  if (categoryBreakdownChart) categoryBreakdownChart.destroy();
  if (!categories.length || typeof Chart === "undefined") {
    document.querySelector("#breakdown-category-title").textContent = "—";
    document.querySelector("#breakdown-category-total").textContent = "—";
    document.querySelector("#breakdown-entry-count").textContent = "";
    breakdownEntryList.replaceChildren(
      textElement("p", "loading", "Nenhum lançamento encontrado neste mês."),
    );
    return;
  }
  const shell = canvas.closest(".category-breakdown-chart-shell");
  shell.style.height = `${Math.max(360, categories.length * 34)}px`;
  categoryBreakdownChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: categories.map(category => category.category_name),
      datasets: [{
        label: "Total da categoria",
        data: categories.map(category => Number(category.total)),
        backgroundColor: categories.map((_, index) =>
          colorWithAlpha(chartPalette[index % chartPalette.length], 0.72),
        ),
        borderColor: categories.map((_, index) =>
          chartPalette[index % chartPalette.length],
        ),
        borderWidth: 1,
        borderRadius: 7,
        categorySlugs: categories.map(category => category.category),
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      onClick: (_, elements) => {
        if (!elements.length) return;
        selectBreakdownCategory(categories[elements[0].index].category);
      },
      plugins: {
        legend: {display: false},
        tooltip: {
          padding: 12,
          callbacks: {
            label: context => {
              const category = categories[context.dataIndex];
              return `${formatCurrency(category.total)} · ${category.count} ${category.count === 1 ? "lançamento" : "lançamentos"}`;
            },
          },
        },
      },
      scales: {
        x: {beginAtZero: true, ticks: {callback: value => formatCompactCurrency(value)}},
        y: {grid: {display: false}, ticks: {font: {size: 11}}},
      },
    },
  });
  const selectedCategory = categories.some(item => item.category === previousCategory)
    ? previousCategory
    : categories[0].category;
  selectBreakdownCategory(selectedCategory);
}

async function loadMonthlyBreakdown() {
  if (!breakdownMonth.value) return;
  breakdownEntryList.replaceChildren(
    textElement("p", "loading", "Carregando lançamentos…"),
  );
  try {
    renderMonthlyBreakdown(
      await api(`/api/analytics/monthly/${breakdownMonth.value}/breakdown`),
    );
  } catch (error) {
    breakdownEntryList.replaceChildren(
      textElement("p", "diagnostic-error", error.message),
    );
  }
}

function renderChart(data) {
  const rows = data.series;
  const expenseIncomeRows = data.expense_income_projection || [];
  const labels = [...new Set([
    ...rows.map(item => item.month),
    ...expenseIncomeRows.map(item => item.month),
  ])].sort();
  const categoryNames = [...new Set(rows.map(item => item.category))].sort();
  document.querySelector("#chart-actual-total").textContent = formatCurrency(
    rows.filter(item => item.kind === "actual").reduce((total, item) => total + Number(item.total), 0),
  );
  document.querySelector("#chart-projected-total").textContent = formatCurrency(
    rows.filter(item => item.kind === "projected").reduce((total, item) => total + Number(item.total), 0),
  );
  document.querySelector("#chart-category-count").textContent = String(categoryNames.length);
  renderBalanceHistory(data);
  if (data.reference_month) {
    const referenceLabel = new Date(`${data.reference_month}-01T00:00:00Z`).toLocaleDateString(
      "pt-BR", {month: "long", year: "numeric", timeZone: "UTC"},
    );
    document.querySelector("#dashboard-note").textContent =
      `${referenceLabel} é o mês-base. As maiores categorias ficam na base de cada coluna; passe sobre uma faixa ou sobre o nome do mês para ver os detalhes.`;
  }
  document.querySelector("#chart-empty").hidden = labels.length > 0;
  if (monthlyChart) monthlyChart.destroy();
  if (!labels.length || typeof Chart === "undefined") return;
  const displayLabels = labels.map(month => new Date(`${month}-01T00:00:00Z`).toLocaleDateString(
    "pt-BR", {month: "short", year: "2-digit", timeZone: "UTC"},
  ));
  const monthlyTotals = new Map(labels.map(month => [
    month,
    rows
      .filter(item => item.month === month)
      .reduce((total, item) => total + Number(item.total), 0),
  ]));
  const monthlyLayouts = new Map(labels.map(month => {
    const layout = new Map();
    const groupedRows = new Map();
    rows
      .filter(item => item.month === month && Number(item.total) !== 0)
      .forEach(item => {
        const current = groupedRows.get(item.category) || {
          ...item,
          amount: 0,
          kinds: new Set(),
        };
        current.amount += Number(item.total);
        current.kinds.add(item.kind);
        groupedRows.set(item.category, current);
      });
    const monthRows = [...groupedRows.values()].map(item => ({
      ...item,
      kind: item.kinds.size === 1 ? [...item.kinds][0] : "mixed",
    }));
    let positiveBase = 0;
    monthRows
      .filter(item => item.amount > 0)
      .sort((left, right) => right.amount - left.amount)
      .forEach(item => {
        layout.set(item.category, {
          ...item,
          range: [positiveBase, positiveBase + item.amount],
        });
        positiveBase += item.amount;
      });
    let negativeBase = 0;
    monthRows
      .filter(item => item.amount < 0)
      .sort((left, right) => left.amount - right.amount)
      .forEach(item => {
        layout.set(item.category, {
          ...item,
          range: [negativeBase + item.amount, negativeBase],
        });
        negativeBase += item.amount;
      });
    return [month, layout];
  }));
  const datasets = categoryNames.map((category, index) => {
    const color = chartPalette[index % chartPalette.length];
    const categoryRows = labels.map(month => monthlyLayouts.get(month).get(category));
    return {
      label: category,
      data: categoryRows.map(item => item?.range || null),
      amounts: categoryRows.map(item => item?.amount || 0),
      backgroundColor: categoryRows.map(item =>
        item?.kind === "projected"
          ? colorWithAlpha(color, 0.38)
          : item?.kind === "mixed" ? colorWithAlpha(color, 0.7) : color,
      ),
      borderColor: color,
      borderWidth: categoryRows.map(item => item?.kind === "projected" ? 1 : 0),
      kinds: categoryRows.map(item => item?.kind || null),
      grouped: false,
      barPercentage: 0.76,
      categoryPercentage: 0.82,
      borderSkipped: false,
      borderRadius: 0,
      inflateAmount: 1,
    };
  });
  if (data.include_expense_income) {
    const valuesByMonth = new Map(expenseIncomeRows.map(item => [item.month, item]));
    const projectionRows = labels.map(month => valuesByMonth.get(month));
    const guardadoMovements = projectionRows.map(item => item ? Number(item.total) : null);
    const savedBalances = projectionRows.map(item => item ? Number(item.saved_balance) : null);
    if (includeMonthlyBalance.checked) {
      datasets.push({
        type: "line",
        label: "Saldo mensal",
        data: guardadoMovements,
        amounts: projectionRows.map(item => item ? Number(item.total) : 0),
        expenses: projectionRows.map(item => item ? Number(item.expenses) : 0),
        incomes: projectionRows.map(item => item ? Number(item.income) : 0),
        isExpenseIncome: true,
        borderColor: "#17231e",
        backgroundColor: guardadoMovements.map(value => value !== null && value < 0 ? "#a54131" : "#2e7659"),
        pointBorderColor: "#ffffff",
        pointBorderWidth: 2,
        borderWidth: 3,
        pointRadius: 4,
        pointHoverRadius: 6,
        tension: 0.25,
        order: -1,
        segment: {
          borderColor: context => context.p1.parsed.y < 0 ? "#a54131" : "#2e7659",
        },
      });
    }
    if (includeAccumulatedBalance.checked) {
      datasets.push({
        type: "line",
        label: "Saldo acumulado",
        data: savedBalances,
        amounts: savedBalances.map(value => value ?? 0),
        isSavedBalance: true,
        yAxisID: "ySaved",
        borderColor: "#9b6b21",
        backgroundColor: "#9b6b21",
        pointBorderColor: "#ffffff",
        pointBorderWidth: 2,
        borderWidth: 3,
        borderDash: [7, 5],
        pointRadius: 4,
        pointHoverRadius: 6,
        tension: 0.25,
        order: -2,
      });
    }
  }
  const monthAxisTooltip = {
    id: "monthAxisTooltip",
    afterEvent(chart, args) {
      const event = args.event;
      if (event.type === "mouseout") {
        chart.tooltip.setActiveElements([], {x: 0, y: 0});
        chart.setActiveElements([]);
        args.changed = true;
        return;
      }
      const intersecting = chart.getElementsAtEventForMode(
        event,
        "nearest",
        {intersect: true},
        false,
      );
      if (intersecting.length) return;
      const xScale = chart.scales.x;
      const overMonthLabel = event.x >= xScale.left
        && event.x <= xScale.right
        && event.y >= chart.chartArea.bottom
        && event.y <= xScale.bottom;
      if (!overMonthLabel) {
        chart.tooltip.setActiveElements([], {x: 0, y: 0});
        chart.setActiveElements([]);
        args.changed = true;
        return;
      }
      const monthIndex = Math.round(xScale.getValueForPixel(event.x));
      if (monthIndex < 0 || monthIndex >= labels.length) return;
      const monthElements = chart.data.datasets.flatMap((dataset, datasetIndex) =>
        Number(dataset.amounts[monthIndex]) !== 0 ? [{datasetIndex, index: monthIndex}] : [],
      );
      chart.tooltip.setActiveElements(monthElements, {
        x: xScale.getPixelForValue(monthIndex),
        y: chart.chartArea.bottom,
      });
      chart.setActiveElements(monthElements);
      args.changed = true;
    },
  };
  monthlyChart = new Chart(document.querySelector("#monthly-chart"), {
    type: "bar",
    data: {labels: displayLabels, datasets},
    plugins: [monthAxisTooltip],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {mode: "nearest", intersect: true},
      plugins: {
        legend: {
          position: "bottom",
          labels: {boxWidth: 12, usePointStyle: true, padding: 20, font: {size: 13}},
        },
        tooltip: {
          enabled: true,
          mode: "nearest",
          intersect: true,
          padding: 14,
          titleFont: {size: 14},
          bodyFont: {size: 13},
          bodySpacing: 7,
          filter: context => Number(context.dataset.amounts[context.dataIndex]) !== 0,
          callbacks: {
            label: context => {
              if (context.dataset.isSavedBalance) {
                return `Saldo acumulado do guardado: ${formatCurrency(context.raw)}`;
              }
              if (context.dataset.isExpenseIncome) {
                const index = context.dataIndex;
                const movement = context.dataset.amounts[index];
                const destination = movement < 0 ? "Sai do guardado" : "Entra no guardado";
                return [
                  `${destination}: ${formatCurrency(Math.abs(movement))}`,
                  `Gastos: ${formatCurrency(context.dataset.expenses[index])}`,
                  `Rendimento: ${formatCurrency(context.dataset.incomes[index])}`,
                ];
              }
              const kind = context.dataset.kinds[context.dataIndex] === "projected"
                ? "previsto"
                : context.dataset.kinds[context.dataIndex] === "mixed"
                  ? "real + previsto"
                  : "real";
              const amount = context.dataset.amounts[context.dataIndex];
              const percentage = formatPercentage(
                amount,
                monthlyTotals.get(labels[context.dataIndex]),
              );
              return `${context.dataset.label}: ${formatCurrency(amount)} · ${percentage} do mês · ${kind}`;
            },
            footer: contexts => {
              const index = contexts[0]?.dataIndex;
              if (index === undefined) return "";
              return `Total do mês: ${formatCurrency(monthlyTotals.get(labels[index]) || 0)}`;
            },
          },
        },
      },
      scales: {
        x: {stacked: false, grid: {display: false}, ticks: {font: {size: 12}}},
        y: {
          stacked: false,
          beginAtZero: true,
          ticks: {font: {size: 12}, callback: value => formatCurrency(value)},
        },
        ySaved: {
          display: data.include_expense_income && includeAccumulatedBalance.checked,
          position: "right",
          beginAtZero: false,
          grid: {drawOnChartArea: false},
          ticks: {font: {size: 12}, callback: value => formatCurrency(value)},
        },
      },
    },
  });
}

async function loadDashboard() {
  try {
    const query = new URLSearchParams({
      months: dashboardMonths.value,
      include_card: String(includeCard.checked),
      include_manual: String(includeManual.checked),
      include_actual: String(includeActual.checked),
      include_projected: String(includeProjected.checked),
      include_expense_income: "true",
    });
    const data = await api(`/api/analytics/monthly?${query}`);
    latestDashboardData = data;
    renderChart(data);
    syncBreakdownMonths(data);
    if (data.reference_month) {
      const [year, month] = data.reference_month.split("-").map(Number);
      const nextMonth = new Date(Date.UTC(year, month, 1)).toISOString().slice(0, 7);
      if (!manualExpenseMonth.value || manualExpenseMonth.value <= data.reference_month) {
        manualExpenseMonth.value = nextMonth;
      }
      manualExpenseRecurrenceEnd.min = manualExpenseMonth.value;
      balanceMonth.max = data.reference_month;
      if (!balanceMonth.value || balanceMonth.value > data.reference_month) {
        balanceMonth.value = data.reference_month;
      }
      syncExpenseTypeMonth();
    }
    await loadMonthlyBreakdown();
    return data;
  } catch (error) {
    document.querySelector("#chart-empty").hidden = false;
    document.querySelector("#chart-empty").textContent = error.message;
  }
}

refreshTransactions.addEventListener("click", loadTransactions);
dashboardMonths.addEventListener("change", loadDashboard);
includeCard.addEventListener("change", loadDashboard);
includeManual.addEventListener("change", loadDashboard);
includeActual.addEventListener("change", loadDashboard);
includeProjected.addEventListener("change", loadDashboard);
includeMonthlyBalance.addEventListener("change", loadDashboard);
includeAccumulatedBalance.addEventListener("change", loadDashboard);
compoundInterestEnabled.addEventListener("change", () => {
  compoundInterestRate.disabled = !compoundInterestEnabled.checked;
  if (latestDashboardData) renderBalanceHistory(latestDashboardData);
});
compoundInterestRate.addEventListener("input", () => {
  if (latestDashboardData && compoundInterestEnabled.checked) {
    renderBalanceHistory(latestDashboardData);
  }
});
breakdownMonth.addEventListener("change", loadMonthlyBreakdown);
breakdownSource.addEventListener("change", renderBreakdownSource);
breakdownKind.addEventListener("change", renderBreakdownSource);
breakdownCategory.addEventListener("change", () => {
  selectBreakdownCategory(breakdownCategory.value);
});

const paymentLabels = {
  credito: "Cartão de crédito",
  pix: "PIX",
  debito: "Débito",
  dinheiro: "Dinheiro",
  transferencia: "Transferência",
  outro: "Outro",
};

const recurrenceLabels = {
  none: "Única",
  unlimited: "Infinita",
  until: "Finita",
};
const expenseTypeLabels = {
  actual: "Real",
  planned: "Previsto",
};

function setExpenseRecurrenceFields(mode, endMonth = "") {
  manualExpenseRecurrenceMode.value = mode || "none";
  const limited = manualExpenseRecurrenceMode.value === "until";
  manualExpenseRecurrenceEndField.hidden = !limited;
  manualExpenseRecurrenceEnd.required = limited;
  manualExpenseRecurrenceEnd.min = manualExpenseMonth.value;
  manualExpenseRecurrenceEnd.value = limited ? endMonth : "";
}

function resetExpenseEditor() {
  editingExpenseId = null;
  manualExpenseFormTitle.textContent = "Adicionar gasto real ou previsto";
  manualExpenseSubmit.textContent = "Adicionar lançamento";
  manualExpenseCancel.hidden = true;
  manualExpenseDescription.value = "";
  manualExpenseAmount.value = "";
  manualExpenseType.value = "actual";
  manualExpensePayment.value = "credito";
  setExpenseRecurrenceFields("none");
}

function editExpense(item) {
  editingExpenseId = item.id;
  manualExpenseFormTitle.textContent = "Editar gasto real ou previsto";
  manualExpenseSubmit.textContent = "Salvar alterações";
  manualExpenseCancel.hidden = false;
  manualExpenseMonth.value = item.month;
  manualExpenseDescription.value = item.description;
  manualExpenseAmount.value = item.amount;
  manualExpenseCategory.value = item.category_slug;
  manualExpenseType.value = item.expense_type;
  manualExpensePayment.value = item.payment_method;
  setExpenseRecurrenceFields(item.recurrence_mode || "none", item.recurrence_end_month || "");
  manualExpenseForm.scrollIntoView({behavior: "smooth", block: "start"});
  manualExpenseDescription.focus({preventScroll: true});
}

function renderManualExpenses(items) {
  manualExpenseList.replaceChildren();
  if (!items.length) {
    manualExpenseList.append(textElement("p", "loading", "Nenhum lançamento manual."));
    return;
  }
  items.forEach(item => {
    const row = document.createElement("article");
    row.className = "manual-expense-item";
    const identity = document.createElement("div");
    identity.append(
      textElement("strong", "", item.description),
      textElement(
        "small",
        "",
        `${item.month} · ${item.category_name} · ${paymentLabels[item.payment_method]}`,
      ),
    );
    const recurrenceMode = item.recurrence_mode || "none";
    const recurrenceText = recurrenceMode === "until"
      ? `${recurrenceLabels.until} · ${item.recurrence_end_month}`
      : recurrenceLabels[recurrenceMode];
    const recurrenceTag = textElement("span", "recurrence-tag", recurrenceText);
    const expenseTags = document.createElement("div");
    expenseTags.className = "expense-tags";
    const typeText = item.covered_by_invoice && item.expense_type === "planned"
      ? "Previsto · mês já fechado"
      : expenseTypeLabels[item.expense_type] || "Previsto";
    const typeTag = textElement(
      "span",
      item.expense_type === "actual" ? "expense-type-tag actual" : "expense-type-tag",
      typeText,
    );
    expenseTags.append(typeTag, recurrenceTag);
    const actions = document.createElement("div");
    actions.className = "expense-item-actions";
    const edit = textElement("button", "dark", "Editar");
    edit.type = "button";
    edit.addEventListener("click", () => editExpense(item));
    const remove = textElement("button", "secondary", "Remover");
    remove.type = "button";
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try {
        const response = await api(`/api/cash-flow/expenses/${item.id}`, {method: "DELETE"});
        if (editingExpenseId === item.id) resetExpenseEditor();
        notify(response.message);
        await Promise.all([loadManualExpenses(), loadDashboard(), loadMonthlySummary()]);
      } catch (error) {
        notify(error.message, true);
        remove.disabled = false;
      }
    });
    actions.append(edit, remove);
    row.append(
      identity,
      textElement("b", "", formatCurrency(item.amount)),
      actions,
      expenseTags,
    );
    manualExpenseList.append(row);
  });
}

async function loadManualExpenses() {
  refreshManualExpenses.disabled = true;
  try {
    const response = await api("/api/cash-flow/expenses?limit=100");
    renderManualExpenses(response.items);
  } catch (error) {
    manualExpenseList.replaceChildren(textElement("p", "diagnostic-error", error.message));
  } finally {
    refreshManualExpenses.disabled = false;
  }
}

manualExpenseForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = manualExpenseForm.querySelector(".primary");
  button.disabled = true;
  try {
    const expenseId = editingExpenseId;
    const response = await api(
      expenseId ? `/api/cash-flow/expenses/${expenseId}` : "/api/cash-flow/expenses",
      {
      method: expenseId ? "PUT" : "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        month: manualExpenseMonth.value,
        description: manualExpenseDescription.value,
        amount: manualExpenseAmount.value,
        category_slug: manualExpenseCategory.value,
        payment_method: manualExpensePayment.value,
        expense_type: manualExpenseType.value,
        recurrence_mode: manualExpenseRecurrenceMode.value,
        recurrence_end_month: manualExpenseRecurrenceMode.value === "until"
          ? manualExpenseRecurrenceEnd.value
          : null,
      }),
    });
    resetExpenseEditor();
    notify(response.message);
    await Promise.all([loadManualExpenses(), loadDashboard(), loadMonthlySummary()]);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
});

manualExpenseCancel.addEventListener("click", resetExpenseEditor);

manualExpenseRecurrenceMode.addEventListener("change", () => {
  const limited = manualExpenseRecurrenceMode.value === "until";
  manualExpenseRecurrenceEndField.hidden = !limited;
  manualExpenseRecurrenceEnd.required = limited;
  manualExpenseRecurrenceEnd.min = manualExpenseMonth.value;
  if (!limited) manualExpenseRecurrenceEnd.value = "";
});
function syncExpenseTypeMonth() {
  manualExpenseMonth.min = "";
  manualExpenseMonth.max = "";
  manualExpenseRecurrenceEnd.min = manualExpenseMonth.value;
}
manualExpenseType.addEventListener("change", syncExpenseTypeMonth);
manualExpenseMonth.addEventListener("change", () => {
  manualExpenseRecurrenceEnd.min = manualExpenseMonth.value;
});

refreshManualExpenses.addEventListener("click", loadManualExpenses);

function renderMonthlySummary(summary, updateInputs = true) {
  if (updateInputs) {
    monthlyIncome.value = summary.income;
    savedBase.value = summary.saved_base;
  }
  document.querySelector("#balance-expenses").textContent = formatCurrency(summary.total_expenses);
  const cardOnly = summary.include_manual === false;
  document.querySelector("#balance-expense-sources").textContent = cardOnly
    ? `Cartão ${formatCurrency(summary.card_expenses)} · outros ${formatCurrency(summary.manual_expenses)} fora da simulação`
    : `Cartão ${formatCurrency(summary.card_expenses)} · outros ${formatCurrency(summary.manual_expenses)}`;
  const result = Number(summary.result);
  const resultElement = document.querySelector("#balance-result");
  resultElement.textContent = formatCurrency(result);
  resultElement.classList.toggle("negative", result < 0);
  document.querySelector("#balance-saved").textContent = formatCurrency(
    cardOnly ? Number(summary.saved_base) + result : summary.saved_total,
  );
  document.querySelector("#balance-applied-state").textContent = cardOnly
    ? "simulação: guardado anterior + resultado somente do cartão"
    : summary.applied_result === null
      ? "resultado ainda não aplicado"
      : `${formatCurrency(summary.applied_result)} aplicado neste mês`;
  applyMonthResult.disabled = cardOnly;
  applyMonthResult.textContent = cardOnly
    ? "Simulação — não aplicável"
    : "Adicionar resultado ao guardado";
}

async function loadMonthlySummary() {
  if (!balanceMonth.value) return;
  try {
    const includeManual = balanceExpenseScope.value !== "card_only";
    renderMonthlySummary(await api(
      `/api/cash-flow/monthly/${balanceMonth.value}?include_manual=${includeManual}`,
    ));
  } catch (error) {
    notify(error.message, true);
  }
}

monthlyBalanceForm.addEventListener("submit", async event => {
  event.preventDefault();
  const button = monthlyBalanceForm.querySelector(".dark");
  button.disabled = true;
  try {
    const response = await api(`/api/cash-flow/monthly/${balanceMonth.value}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({income: monthlyIncome.value, saved_base: savedBase.value}),
    });
    notify(response.message);
    await loadMonthlySummary();
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
});

balanceMonth.addEventListener("change", loadMonthlySummary);
balanceExpenseScope.addEventListener("change", loadMonthlySummary);

applyMonthResult.addEventListener("click", async () => {
  if (balanceExpenseScope.value === "card_only") {
    notify("A simulação somente do cartão não pode ser aplicada ao guardado.", true);
    return;
  }
  applyMonthResult.disabled = true;
  try {
    await api(`/api/cash-flow/monthly/${balanceMonth.value}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({income: monthlyIncome.value, saved_base: savedBase.value}),
    });
    const response = await api(`/api/cash-flow/monthly/${balanceMonth.value}/apply-result`, {
      method: "POST",
    });
    notify(response.message);
    await loadMonthlySummary();
  } catch (error) {
    notify(error.message, true);
  } finally {
    applyMonthResult.disabled = balanceExpenseScope.value === "card_only";
  }
});

const connectionList = document.querySelector("#connection-list");
const logList = document.querySelector("#log-list");
const logCount = document.querySelector("#log-count");
const refreshDiagnostics = document.querySelector("#refresh-diagnostics");

async function loadDiagnostics() {
  refreshDiagnostics.disabled = true;
  try {
    const [connections, logs] = await Promise.all([
      api("/api/system/connections"),
      api("/api/system/logs?limit=40"),
    ]);
    connectionList.replaceChildren();
    connections.components.forEach(item => {
      const card = document.createElement("article");
      card.className = `connection ${item.status}`;
      card.append(
        textElement("span", "connection-dot", ""),
        textElement("strong", "", item.component),
        textElement("small", "", item.detail),
        textElement("b", "", `${item.latency_ms.toFixed(2)} ms`),
      );
      connectionList.append(card);
    });
    logList.replaceChildren();
    logs.events.forEach(event => {
      const row = document.createElement("code");
      row.textContent = JSON.stringify(event);
      logList.append(row);
    });
    if (!logs.events.length) logList.append(textElement("p", "loading", "Nenhum evento registrado."));
    logCount.textContent = String(logs.events.length);
  } catch (error) {
    connectionList.replaceChildren(textElement("p", "diagnostic-error", error.message));
  } finally {
    refreshDiagnostics.disabled = false;
  }
}

async function initializeFinancialWorkspace() {
  try {
    const response = await api("/api/categories");
    categories = response.items;
    categoryFilterOptions();
    await loadDashboard();
    await Promise.all([
      loadTransactions(),
      loadManualExpenses(),
      loadMonthlySummary(),
    ]);
  } catch (error) {
    notify(error.message, true);
  }
}

refreshDiagnostics.addEventListener("click", loadDiagnostics);
loadDiagnostics();
initializeFinancialWorkspace();
