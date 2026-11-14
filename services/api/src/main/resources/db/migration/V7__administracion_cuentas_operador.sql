CREATE TABLE idempotencia_accion_operador (
    operador_id UUID NOT NULL REFERENCES cuenta(id) ON DELETE RESTRICT,
    operacion VARCHAR(32) NOT NULL,
    clave_hash CHAR(64) NOT NULL,
    creada_en TIMESTAMPTZ NOT NULL,
    estado_envio VARCHAR(16) NOT NULL,
    revision_acceso BIGINT,
    vence_en TIMESTAMPTZ,
    CONSTRAINT idempotencia_accion_operador_pk
        PRIMARY KEY (operador_id, operacion, clave_hash),
    CONSTRAINT idempotencia_accion_operador_operacion_ck
        CHECK (operacion IN ('REEMITIR_INVITACION', 'REACTIVAR', 'SOLICITAR_RECUPERACION')),
    CONSTRAINT idempotencia_accion_operador_clave_ck
        CHECK (clave_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_accion_operador_envio_ck
        CHECK (estado_envio IN ('ENVIANDO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO', 'DESHABILITADO')),
    CONSTRAINT idempotencia_accion_operador_revision_ck
        CHECK (revision_acceso IS NULL OR revision_acceso >= 0)
);

CREATE INDEX idempotencia_accion_operador_invitaciones_idx
    ON idempotencia_accion_operador (operador_id, creada_en)
    WHERE operacion IN ('REEMITIR_INVITACION', 'REACTIVAR');

CREATE INDEX idempotencia_accion_operador_recuperacion_idx
    ON idempotencia_accion_operador (operador_id, creada_en)
    WHERE operacion = 'SOLICITAR_RECUPERACION';

INSERT INTO idempotencia_accion_operador (
    operador_id, operacion, clave_hash, creada_en, estado_envio, revision_acceso, vence_en)
SELECT i.operador_id,
       'REEMITIR_INVITACION',
       i.clave_reemision_hash,
       i.generado_en,
       i.estado_envio,
       c.revision_acceso,
       i.vence_en
FROM invitacion_operador i
JOIN cuenta c ON c.id = i.operador_id
WHERE i.reemision_usada = TRUE;

CREATE TABLE recuperacion_contrasena_operador (
    operador_id UUID PRIMARY KEY REFERENCES cuenta(id) ON DELETE RESTRICT,
    token_hash CHAR(64) NOT NULL UNIQUE,
    generado_en TIMESTAMPTZ NOT NULL,
    vence_en TIMESTAMPTZ NOT NULL,
    consumido_en TIMESTAMPTZ,
    estado_envio VARCHAR(16) NOT NULL,
    intento_iniciado_en TIMESTAMPTZ NOT NULL,
    CONSTRAINT recuperacion_contrasena_token_hash_ck
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT recuperacion_contrasena_vigencia_ck
        CHECK (vence_en = generado_en + INTERVAL '30 minutes'),
    CONSTRAINT recuperacion_contrasena_consumo_ck
        CHECK (consumido_en IS NULL OR consumido_en >= generado_en),
    CONSTRAINT recuperacion_contrasena_estado_envio_ck
        CHECK (estado_envio IN ('ENVIANDO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO', 'DESHABILITADO'))
);

ALTER TABLE invitacion_operador
    DROP CONSTRAINT invitacion_operador_reemision_ck,
    DROP COLUMN reemision_usada,
    DROP COLUMN clave_reemision_hash;
