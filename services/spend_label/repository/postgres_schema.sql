CREATE SCHEMA IF NOT EXISTS spend_label;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS spend_label.categorias (
    id SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug VARCHAR(50) NOT NULL UNIQUE,
    nome VARCHAR(100) NOT NULL,
    categoria_pai_id SMALLINT REFERENCES spend_label.categorias(id),
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT categorias_slug_formato_check
        CHECK (slug ~ '^[a-z0-9]+(?:_[a-z0-9]+)*$'),
    CONSTRAINT categorias_nome_preenchido_check
        CHECK (BTRIM(nome) <> ''),
    CONSTRAINT categorias_sem_auto_parentesco_check
        CHECK (categoria_pai_id IS NULL OR categoria_pai_id <> id)
);

INSERT INTO spend_label.categorias (slug, nome)
VALUES
    ('alimentacao', 'Alimentação'),
    ('assinaturas', 'Assinaturas'),
    ('educacao', 'Educação'),
    ('eletronicos', 'Eletrônicos'),
    ('encargos', 'Encargos'),
    ('entretenimento', 'Entretenimento'),
    ('lazer', 'Lazer'),
    ('moradia', 'Moradia'),
    ('outros', 'Outros'),
    ('restaurante', 'Restaurante'),
    ('saude', 'Saúde'),
    ('servicos', 'Serviços'),
    ('transporte', 'Transporte'),
    ('viagem', 'Viagem'),
    ('vestuario', 'Vestuário')
ON CONFLICT (slug) DO UPDATE
SET nome = EXCLUDED.nome;

CREATE TABLE IF NOT EXISTS spend_label.estabelecimentos (
    id VARCHAR(32) PRIMARY KEY,
    nome_canonico VARCHAR(120) NOT NULL,
    categoria_padrao_id SMALLINT REFERENCES spend_label.categorias(id),
    categoria_padrao_confirmada BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT estabelecimentos_nome_preenchido_check
        CHECK (BTRIM(nome_canonico) <> ''),
    CONSTRAINT estabelecimentos_categoria_confirmada_check
        CHECK (
            NOT categoria_padrao_confirmada
            OR categoria_padrao_id IS NOT NULL
        )
);

CREATE TABLE IF NOT EXISTS spend_label.aliases_estabelecimento (
    alias_hash VARCHAR(32) PRIMARY KEY,
    estabelecimento_id VARCHAR(32) NOT NULL
        REFERENCES spend_label.estabelecimentos(id) ON DELETE RESTRICT,
    descricao_normalizada VARCHAR(180) NOT NULL UNIQUE,
    origem VARCHAR(20) NOT NULL DEFAULT 'importacao'
        CHECK (origem IN ('importacao', 'manual', 'similaridade')),
    confirmado BOOLEAN NOT NULL DEFAULT FALSE,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT aliases_descricao_preenchida_check
        CHECK (BTRIM(descricao_normalizada) <> '')
);

CREATE INDEX IF NOT EXISTS aliases_estabelecimento_busca_trgm_idx
    ON spend_label.aliases_estabelecimento
    USING GIN (descricao_normalizada gin_trgm_ops);

CREATE INDEX IF NOT EXISTS aliases_estabelecimento_canonico_idx
    ON spend_label.aliases_estabelecimento(estabelecimento_id);

UPDATE spend_label.aliases_estabelecimento AS alias
SET descricao_normalizada = UPPER(alias.descricao_normalizada),
    atualizado_em = CURRENT_TIMESTAMP
WHERE alias.descricao_normalizada <> UPPER(alias.descricao_normalizada)
  AND NOT EXISTS (
      SELECT 1
      FROM spend_label.aliases_estabelecimento AS collision
      WHERE collision.alias_hash <> alias.alias_hash
        AND collision.descricao_normalizada = UPPER(alias.descricao_normalizada)
  );

CREATE TABLE IF NOT EXISTS spend_label.classificacoes_transacao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transacao_id BIGINT NOT NULL
        REFERENCES financeiro.transacoes_versao(id) ON DELETE CASCADE,
    categoria_id SMALLINT NOT NULL REFERENCES spend_label.categorias(id),
    origem VARCHAR(30) NOT NULL
        CHECK (
            origem IN (
                'manual',
                'regra_estabelecimento',
                'modelo',
                'parser'
            )
        ),
    confianca NUMERIC(5,4)
        CHECK (confianca IS NULL OR confianca BETWEEN 0 AND 1),
    modelo_versao VARCHAR(80),
    confirmada BOOLEAN NOT NULL DEFAULT FALSE,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmada_em TIMESTAMPTZ,
    CONSTRAINT classificacoes_modelo_metadados_check
        CHECK (
            origem <> 'modelo'
            OR (confianca IS NOT NULL AND modelo_versao IS NOT NULL)
        ),
    CONSTRAINT classificacoes_manual_confirmada_check
        CHECK (origem <> 'manual' OR confirmada),
    CONSTRAINT classificacoes_confirmacao_data_check
        CHECK (
            (confirmada AND confirmada_em IS NOT NULL)
            OR (NOT confirmada AND confirmada_em IS NULL)
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS classificacoes_transacao_ativa_idx
    ON spend_label.classificacoes_transacao(transacao_id)
    WHERE ativa;

CREATE INDEX IF NOT EXISTS classificacoes_transacao_categoria_idx
    ON spend_label.classificacoes_transacao(categoria_id);

CREATE TABLE IF NOT EXISTS spend_label.recorrencias_transacao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transacao_id BIGINT NOT NULL
        REFERENCES financeiro.transacoes_versao(id) ON DELETE CASCADE,
    modo VARCHAR(20) NOT NULL CHECK (modo IN ('unlimited', 'until')),
    fim_mes DATE,
    ativa BOOLEAN NOT NULL DEFAULT TRUE,
    criada_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    encerrada_em TIMESTAMPTZ,
    CONSTRAINT recorrencias_prazo_check CHECK (
        (modo = 'unlimited' AND fim_mes IS NULL)
        OR (
            modo = 'until'
            AND fim_mes IS NOT NULL
            AND fim_mes = DATE_TRUNC('month', fim_mes)::date
        )
    ),
    CONSTRAINT recorrencias_encerramento_check CHECK (
        (ativa AND encerrada_em IS NULL)
        OR (NOT ativa AND encerrada_em IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS recorrencias_transacao_ativa_idx
    ON spend_label.recorrencias_transacao(transacao_id)
    WHERE ativa;

CREATE INDEX IF NOT EXISTS recorrencias_fim_mes_idx
    ON spend_label.recorrencias_transacao(fim_mes)
    WHERE ativa;

-- Cada identificador extraído começa como seu próprio estabelecimento. Quando o
-- usuário confirmar que aliases diferentes representam a mesma empresa, basta
-- apontá-los para um único registro em estabelecimentos.
INSERT INTO spend_label.estabelecimentos (id, nome_canonico)
SELECT
    t.estabelecimento_id,
    MIN(t.descricao)
FROM financeiro.transacoes_versao AS t
GROUP BY t.estabelecimento_id
ON CONFLICT (id) DO NOTHING;

INSERT INTO spend_label.aliases_estabelecimento (
    alias_hash,
    estabelecimento_id,
    descricao_normalizada,
    origem,
    confirmado
)
SELECT
    t.estabelecimento_id,
    t.estabelecimento_id,
    MIN(t.descricao_normalizada),
    'importacao',
    FALSE
FROM financeiro.transacoes_versao AS t
GROUP BY t.estabelecimento_id
ON CONFLICT (alias_hash) DO NOTHING;

-- Preserva os rótulos do modelo anterior somente quando a tabela legada existe.
-- Instalações novas não possuem financeiro.rotulos_estabelecimento.
DO $migration$
BEGIN
    IF to_regclass('financeiro.rotulos_estabelecimento') IS NOT NULL THEN
        EXECUTE $sql$
            INSERT INTO spend_label.estabelecimentos (id, nome_canonico)
            SELECT estabelecimento_id, rotulo
            FROM financeiro.rotulos_estabelecimento
            ON CONFLICT (id) DO NOTHING
        $sql$;

        EXECUTE $sql$
            INSERT INTO spend_label.aliases_estabelecimento (
                alias_hash,
                estabelecimento_id,
                descricao_normalizada,
                origem,
                confirmado
            )
            SELECT
                estabelecimento_id,
                estabelecimento_id,
                LOWER(BTRIM(rotulo)),
                'manual',
                TRUE
            FROM financeiro.rotulos_estabelecimento
            ON CONFLICT (alias_hash) DO UPDATE
            SET origem = 'manual',
                confirmado = TRUE,
                atualizado_em = CURRENT_TIMESTAMP
        $sql$;

        EXECUTE $sql$
            UPDATE spend_label.estabelecimentos AS e
            SET nome_canonico = r.rotulo,
                categoria_padrao_id = COALESCE(c.id, e.categoria_padrao_id),
                categoria_padrao_confirmada = c.id IS NOT NULL,
                atualizado_em = CURRENT_TIMESTAMP
            FROM financeiro.rotulos_estabelecimento AS r
            LEFT JOIN spend_label.categorias AS c
                ON c.slug = r.categoria_manual
            WHERE e.id = r.estabelecimento_id
        $sql$;
    END IF;
END
$migration$;

CREATE OR REPLACE VIEW spend_label.classificacoes_atuais AS
SELECT
    ct.id,
    ct.transacao_id,
    ct.categoria_id,
    ct.origem,
    ct.confianca,
    ct.modelo_versao,
    ct.confirmada,
    ct.criada_em,
    ct.confirmada_em
FROM spend_label.classificacoes_transacao AS ct
WHERE ct.ativa;

CREATE OR REPLACE VIEW spend_label.transacoes_categorizadas AS
SELECT
    t.*,
    a.estabelecimento_id AS estabelecimento_canonico_id,
    COALESCE(e.nome_canonico, t.descricao) AS estabelecimento_nome,
    COALESCE(
        CASE WHEN ca.confirmada THEN categoria_transacao.slug END,
        CASE
            WHEN e.categoria_padrao_confirmada THEN categoria_padrao.slug
        END,
        t.categoria
    ) AS categoria_efetiva,
    CASE
        WHEN ca.confirmada THEN ca.origem
        WHEN e.categoria_padrao_confirmada THEN 'regra_estabelecimento'
        ELSE 'parser'
    END AS categoria_origem,
    CASE WHEN NOT ca.confirmada THEN categoria_transacao.slug END
        AS categoria_sugerida,
    CASE WHEN NOT ca.confirmada THEN ca.confianca END
        AS sugestao_confianca,
    ca.modelo_versao AS sugestao_modelo_versao
FROM financeiro.transacoes_versao AS t
LEFT JOIN spend_label.aliases_estabelecimento AS a
    ON a.alias_hash = t.estabelecimento_id
LEFT JOIN spend_label.estabelecimentos AS e
    ON e.id = a.estabelecimento_id
LEFT JOIN spend_label.categorias AS categoria_padrao
    ON categoria_padrao.id = e.categoria_padrao_id
LEFT JOIN spend_label.classificacoes_atuais AS ca
    ON ca.transacao_id = t.id
LEFT JOIN spend_label.categorias AS categoria_transacao
    ON categoria_transacao.id = ca.categoria_id;

CREATE OR REPLACE VIEW spend_label.exemplos_treinamento AS
SELECT
    t.id AS transacao_id,
    t.descricao_normalizada,
    t.localidade,
    COALESCE(
        CASE WHEN ca.confirmada THEN categoria_transacao.slug END,
        CASE
            WHEN e.categoria_padrao_confirmada THEN categoria_padrao.slug
        END
    ) AS categoria,
    CASE
        WHEN ca.confirmada THEN ca.origem
        ELSE 'regra_estabelecimento'
    END AS origem_rotulo
FROM financeiro.transacoes_versao AS t
LEFT JOIN spend_label.aliases_estabelecimento AS a
    ON a.alias_hash = t.estabelecimento_id
LEFT JOIN spend_label.estabelecimentos AS e
    ON e.id = a.estabelecimento_id
LEFT JOIN spend_label.categorias AS categoria_padrao
    ON categoria_padrao.id = e.categoria_padrao_id
LEFT JOIN spend_label.classificacoes_atuais AS ca
    ON ca.transacao_id = t.id
LEFT JOIN spend_label.categorias AS categoria_transacao
    ON categoria_transacao.id = ca.categoria_id
WHERE ca.confirmada OR e.categoria_padrao_confirmada;
