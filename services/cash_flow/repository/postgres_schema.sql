CREATE SCHEMA IF NOT EXISTS cash_flow;

CREATE TABLE IF NOT EXISTS cash_flow.lancamentos_manuais (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mes_referencia DATE NOT NULL,
    descricao VARCHAR(180) NOT NULL,
    valor NUMERIC(14,2) NOT NULL CHECK (valor > 0),
    categoria_id SMALLINT NOT NULL REFERENCES spend_label.categorias(id),
    meio_pagamento VARCHAR(20) NOT NULL
        CHECK (meio_pagamento IN ('credito', 'pix', 'debito', 'dinheiro', 'transferencia', 'outro')),
    tipo_lancamento VARCHAR(12) NOT NULL DEFAULT 'actual'
        CHECK (tipo_lancamento IN ('actual', 'planned')),
    origem_previsao_cartao_id BIGINT,
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removido_em TIMESTAMPTZ,
    CONSTRAINT lancamentos_mes_inicio_check
        CHECK (mes_referencia = DATE_TRUNC('month', mes_referencia)::date),
    CONSTRAINT lancamentos_descricao_check CHECK (BTRIM(descricao) <> ''),
    CONSTRAINT lancamentos_remocao_check CHECK (
        (ativo AND removido_em IS NULL)
        OR (NOT ativo AND removido_em IS NOT NULL)
    )
);

ALTER TABLE cash_flow.lancamentos_manuais
    ADD COLUMN IF NOT EXISTS tipo_lancamento VARCHAR(12);

ALTER TABLE cash_flow.lancamentos_manuais
    ADD COLUMN IF NOT EXISTS origem_previsao_cartao_id BIGINT;

UPDATE cash_flow.lancamentos_manuais
SET tipo_lancamento = 'actual'
WHERE tipo_lancamento IS NULL;

ALTER TABLE cash_flow.lancamentos_manuais
    ALTER COLUMN tipo_lancamento SET DEFAULT 'actual',
    ALTER COLUMN tipo_lancamento SET NOT NULL;

ALTER TABLE cash_flow.lancamentos_manuais
    DROP CONSTRAINT IF EXISTS lancamentos_manuais_meio_pagamento_check;

ALTER TABLE cash_flow.lancamentos_manuais
    ADD CONSTRAINT lancamentos_manuais_meio_pagamento_check
    CHECK (meio_pagamento IN (
        'credito', 'pix', 'debito', 'dinheiro', 'transferencia', 'outro'
    ));

ALTER TABLE cash_flow.lancamentos_manuais
    DROP CONSTRAINT IF EXISTS lancamentos_manuais_tipo_lancamento_check;

ALTER TABLE cash_flow.lancamentos_manuais
    ADD CONSTRAINT lancamentos_manuais_tipo_lancamento_check
    CHECK (tipo_lancamento IN ('actual', 'planned'));

CREATE INDEX IF NOT EXISTS lancamentos_manuais_mes_idx
    ON cash_flow.lancamentos_manuais(mes_referencia)
    WHERE ativo;

CREATE INDEX IF NOT EXISTS lancamentos_manuais_categoria_idx
    ON cash_flow.lancamentos_manuais(categoria_id)
    WHERE ativo;

CREATE TABLE IF NOT EXISTS cash_flow.recorrencias_lancamento_manual (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lancamento_id BIGINT NOT NULL
        REFERENCES cash_flow.lancamentos_manuais(id),
    modo VARCHAR(12) NOT NULL CHECK (modo IN ('unlimited', 'until')),
    fim_mes DATE,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    encerrada_em TIMESTAMPTZ,
    CONSTRAINT recorrencia_manual_fim_mes_check CHECK (
        (modo = 'unlimited' AND fim_mes IS NULL)
        OR (
            modo = 'until'
            AND fim_mes IS NOT NULL
            AND fim_mes = DATE_TRUNC('month', fim_mes)::date
        )
    ),
    CONSTRAINT recorrencia_manual_encerramento_check CHECK (
        (ativa AND encerrada_em IS NULL)
        OR (NOT ativa AND encerrada_em IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS recorrencias_lancamento_manual_ativa_idx
    ON cash_flow.recorrencias_lancamento_manual(lancamento_id)
    WHERE ativa;

CREATE TABLE IF NOT EXISTS cash_flow.gastos_previstos_cartao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mes_referencia DATE NOT NULL,
    descricao VARCHAR(180) NOT NULL,
    valor NUMERIC(14,2) NOT NULL CHECK (valor > 0),
    categoria_id SMALLINT NOT NULL REFERENCES spend_label.categorias(id),
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removido_em TIMESTAMPTZ,
    CONSTRAINT gastos_previstos_mes_inicio_check
        CHECK (mes_referencia = DATE_TRUNC('month', mes_referencia)::date),
    CONSTRAINT gastos_previstos_descricao_check CHECK (BTRIM(descricao) <> ''),
    CONSTRAINT gastos_previstos_remocao_check CHECK (
        (ativo AND removido_em IS NULL)
        OR (NOT ativo AND removido_em IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS gastos_previstos_cartao_mes_idx
    ON cash_flow.gastos_previstos_cartao(mes_referencia)
    WHERE ativo;

CREATE UNIQUE INDEX IF NOT EXISTS lancamentos_origem_previsao_cartao_idx
    ON cash_flow.lancamentos_manuais(origem_previsao_cartao_id)
    WHERE origem_previsao_cartao_id IS NOT NULL;

INSERT INTO cash_flow.lancamentos_manuais(
    mes_referencia,
    descricao,
    valor,
    categoria_id,
    meio_pagamento,
    tipo_lancamento,
    origem_previsao_cartao_id,
    criado_em
)
SELECT
    forecast.mes_referencia,
    forecast.descricao,
    forecast.valor,
    forecast.categoria_id,
    'credito',
    'planned',
    forecast.id,
    forecast.criado_em
FROM cash_flow.gastos_previstos_cartao AS forecast
WHERE forecast.ativo
  AND NOT EXISTS (
      SELECT 1
      FROM cash_flow.lancamentos_manuais AS expense
      WHERE expense.origem_previsao_cartao_id = forecast.id
  );

CREATE TABLE IF NOT EXISTS cash_flow.migracoes_schema (
    nome VARCHAR(100) PRIMARY KEY,
    aplicada_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

WITH applied AS (
    INSERT INTO cash_flow.migracoes_schema(nome)
    VALUES ('20260805_future_commitments_are_actual')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
)
UPDATE cash_flow.lancamentos_manuais
SET tipo_lancamento = 'actual'
WHERE origem_previsao_cartao_id IS NULL
  AND EXISTS (SELECT 1 FROM applied);

CREATE TABLE IF NOT EXISTS cash_flow.resumos_mensais (
    mes_referencia DATE PRIMARY KEY,
    rendimento NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (rendimento >= 0),
    guardado_base NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (guardado_base >= 0),
    resultado_aplicado NUMERIC(14,2),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT resumos_mes_inicio_check
        CHECK (mes_referencia = DATE_TRUNC('month', mes_referencia)::date)
);
