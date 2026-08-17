FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY services/invoice_web/requirements.txt /app/invoice-web-requirements.txt
COPY services/ai_agent/requirements.txt /app/ai-agent-requirements.txt
RUN python -m pip install --no-cache-dir -r /app/invoice-web-requirements.txt -r /app/ai-agent-requirements.txt

COPY services/invoice_web /app/services/invoice_web
COPY services/ai_agent /app/services/ai_agent

ENV PYTHONPATH=/app/services/invoice_web:/app/services/ai_agent
WORKDIR /app/services/invoice_web

RUN groupadd --gid 10001 fatura \
    && useradd --uid 10001 --gid fatura --create-home --shell /usr/sbin/nologin fatura \
    && mkdir -p /app/private \
    && chown -R fatura:fatura /app

USER fatura
EXPOSE 5000
CMD ["python", "run_web.py"]
