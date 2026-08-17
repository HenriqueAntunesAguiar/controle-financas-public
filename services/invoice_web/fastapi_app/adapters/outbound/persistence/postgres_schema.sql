CREATE SCHEMA IF NOT EXISTS financeiro;

CREATE TABLE IF NOT EXISTS financeiro.documentos_fatura (
    id UUID PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE financeiro.documentos_fatura
    ADD COLUMN IF NOT EXISTS nome VARCHAR(120);

UPDATE financeiro.documentos_fatura
SET nome = 'Fatura sem nome'
WHERE nome IS NULL OR BTRIM(nome) = '';

ALTER TABLE financeiro.documentos_fatura
    ALTER COLUMN nome SET NOT NULL;

CREATE TABLE IF NOT EXISTS financeiro.versoes_fatura (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    documento_id UUID NOT NULL REFERENCES financeiro.documentos_fatura(id),
    numero_versao INTEGER NOT NULL CHECK (numero_versao > 0),
    conteudo_hash CHAR(64) NOT NULL UNIQUE,
    data_referencia DATE NOT NULL,
    quantidade_transacoes INTEGER NOT NULL CHECK (quantidade_transacoes > 0),
    status_qualidade VARCHAR(20) NOT NULL DEFAULT 'legacy',
    total_extraido NUMERIC(14,2),
    total_lancamentos_pdf NUMERIC(14,2),
    criado_em TIMESTAMPTZ NOT NULL,
    importado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(documento_id, numero_versao)
);

ALTER TABLE financeiro.versoes_fatura
    ADD COLUMN IF NOT EXISTS status_qualidade VARCHAR(20) NOT NULL DEFAULT 'legacy';

ALTER TABLE financeiro.versoes_fatura
    ADD COLUMN IF NOT EXISTS total_extraido NUMERIC(14,2);

ALTER TABLE financeiro.versoes_fatura
    ADD COLUMN IF NOT EXISTS total_lancamentos_pdf NUMERIC(14,2);

CREATE TABLE IF NOT EXISTS financeiro.transacoes_versao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    versao_id BIGINT NOT NULL REFERENCES financeiro.versoes_fatura(id) ON DELETE CASCADE,
    numero_linha INTEGER NOT NULL,
    data_transacao DATE,
    valor NUMERIC(14,2) NOT NULL,
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('compra', 'credito')),
    categoria VARCHAR(100) NOT NULL,
    descricao VARCHAR(180) NOT NULL,
    descricao_normalizada VARCHAR(180) NOT NULL,
    localidade VARCHAR(120),
    estabelecimento_id VARCHAR(32) NOT NULL,
    parcela_atual SMALLINT,
    total_parcelas SMALLINT,
    pagina_origem SMALLINT NOT NULL,
    UNIQUE(versao_id, numero_linha)
);

ALTER TABLE financeiro.transacoes_versao
    ADD COLUMN IF NOT EXISTS descricao VARCHAR(180);

UPDATE financeiro.transacoes_versao
SET descricao = 'Descricao indisponivel'
WHERE descricao IS NULL OR BTRIM(descricao) = '';

ALTER TABLE financeiro.transacoes_versao
    ALTER COLUMN descricao SET NOT NULL;

ALTER TABLE financeiro.transacoes_versao
    ADD COLUMN IF NOT EXISTS descricao_normalizada VARCHAR(180);

UPDATE financeiro.transacoes_versao
SET descricao_normalizada = UPPER(descricao)
WHERE descricao_normalizada IS NULL OR BTRIM(descricao_normalizada) = '';

UPDATE financeiro.transacoes_versao
SET descricao_normalizada = UPPER(descricao_normalizada)
WHERE descricao_normalizada <> UPPER(descricao_normalizada);

ALTER TABLE financeiro.transacoes_versao
    ALTER COLUMN descricao_normalizada SET NOT NULL;

ALTER TABLE financeiro.transacoes_versao
    ADD COLUMN IF NOT EXISTS localidade VARCHAR(120);

CREATE INDEX IF NOT EXISTS transacoes_versao_data_idx
    ON financeiro.transacoes_versao(data_transacao);

CREATE INDEX IF NOT EXISTS transacoes_versao_descricao_idx
    ON financeiro.transacoes_versao(descricao);

CREATE INDEX IF NOT EXISTS transacoes_versao_descricao_normalizada_idx
    ON financeiro.transacoes_versao(descricao_normalizada);
