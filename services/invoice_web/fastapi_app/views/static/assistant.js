const assistantLauncher = document.querySelector("#assistant-launcher");
const assistantPanel = document.querySelector("#assistant-panel");
const assistantClose = document.querySelector("#assistant-close");
const assistantMessages = document.querySelector("#assistant-messages");
const assistantSuggestions = document.querySelector("#assistant-suggestions");
const assistantStatus = document.querySelector("#assistant-status");
const assistantForm = document.querySelector("#assistant-form");
const assistantInput = document.querySelector("#assistant-input");
const assistantSend = document.querySelector("#assistant-send");
const assistantThreadKey = "financial-assistant-thread";
const assistantThreadId = sessionStorage.getItem(assistantThreadKey) || crypto.randomUUID();

sessionStorage.setItem(assistantThreadKey, assistantThreadId);

function setAssistantOpen(open) {
  assistantPanel.classList.toggle("open", open);
  assistantPanel.setAttribute("aria-hidden", String(!open));
  assistantLauncher.setAttribute("aria-expanded", String(open));
  if (open) {
    assistantInput.focus();
    assistantMessages.scrollTop = assistantMessages.scrollHeight;
  } else {
    assistantLauncher.focus();
  }
}

function assistantTimestamp() {
  return new Intl.DateTimeFormat("pt-BR", {hour: "2-digit", minute: "2-digit"}).format(new Date());
}

function appendAssistantMessage(role, content, error = false) {
  const article = document.createElement("article");
  article.className = `assistant-message assistant-message-${role}${error ? " assistant-message-error" : ""}`;
  const body = document.createElement("div");
  const text = document.createElement("p");
  const time = document.createElement("time");
  text.textContent = content;
  time.textContent = assistantTimestamp();
  body.append(text, time);
  if (role === "ai") {
    const avatar = document.createElement("span");
    avatar.className = "assistant-avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "FL";
    article.append(avatar);
  }
  article.append(body);
  assistantMessages.append(article);
  assistantMessages.scrollTop = assistantMessages.scrollHeight;
}

function setAssistantLoading(loading) {
  assistantStatus.hidden = !loading;
  assistantInput.disabled = loading;
  assistantSend.disabled = loading;
}

async function assistantApi(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": token},
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = response.status === 404
      ? "O chat ainda não está conectado ao backend."
      : data.error || "Não foi possível consultar o assistente.";
    throw new Error(message);
  }
  return data;
}

function renderAssistantApproval(approval) {
  const card = document.createElement("section");
  card.className = "assistant-approval";
  const title = document.createElement("strong");
  const description = document.createElement("p");
  const actions = document.createElement("div");
  const approve = document.createElement("button");
  const reject = document.createElement("button");
  title.textContent = "Confirmação necessária";
  description.textContent = approval.description;
  approve.type = "button";
  approve.className = "approve";
  approve.textContent = "Confirmar";
  reject.type = "button";
  reject.className = "reject";
  reject.textContent = "Rejeitar";
  actions.append(reject, approve);
  card.append(title, description, actions);
  assistantMessages.append(card);
  assistantMessages.scrollTop = assistantMessages.scrollHeight;

  [approve, reject].forEach(button => button.addEventListener("click", async () => {
    approve.disabled = true;
    reject.disabled = true;
    setAssistantLoading(true);
    try {
      const decision = button === approve ? "approve" : "reject";
      const data = await assistantApi("/api/assistant/chat/decision", {
        thread_id: assistantThreadId,
        interrupt_id: approval.id,
        decision,
      });
      card.remove();
      appendAssistantMessage("ai", data.answer || data.message || (decision === "approve" ? "Operação confirmada." : "Operação rejeitada."));
      if (data.pending_approval) renderAssistantApproval(data.pending_approval);
    } catch (error) {
      appendAssistantMessage("ai", error.message, true);
      approve.disabled = false;
      reject.disabled = false;
    } finally {
      setAssistantLoading(false);
    }
  }));
}

async function sendAssistantMessage(message) {
  assistantSuggestions.hidden = true;
  appendAssistantMessage("user", message);
  setAssistantLoading(true);
  try {
    const data = await assistantApi("/api/assistant/chat", {
      thread_id: assistantThreadId,
      message,
    });
    appendAssistantMessage("ai", data.answer || data.message || "O assistente não retornou uma resposta.");
    if (data.pending_approval) renderAssistantApproval(data.pending_approval);
  } catch (error) {
    appendAssistantMessage("ai", error.message, true);
  } finally {
    setAssistantLoading(false);
  }
}

assistantLauncher.addEventListener("click", () => setAssistantOpen(true));
assistantClose.addEventListener("click", () => setAssistantOpen(false));
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && assistantPanel.classList.contains("open")) setAssistantOpen(false);
});

assistantSuggestions.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
  assistantInput.value = button.textContent;
  assistantForm.requestSubmit();
}));

assistantInput.addEventListener("input", () => {
  assistantInput.style.height = "auto";
  assistantInput.style.height = `${Math.min(assistantInput.scrollHeight, 110)}px`;
});

assistantInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    assistantForm.requestSubmit();
  }
});

assistantForm.addEventListener("submit", event => {
  event.preventDefault();
  const message = assistantInput.value.trim();
  if (!message || assistantInput.disabled) return;
  assistantInput.value = "";
  assistantInput.style.height = "auto";
  sendAssistantMessage(message);
});
