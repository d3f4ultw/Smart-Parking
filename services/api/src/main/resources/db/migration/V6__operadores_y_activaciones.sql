ALTER TABLE cuenta
    DROP CONSTRAINT cuenta_estado_check,
    DROP CONSTRAINT cuenta_estado_credencial_ck;

ALTER TABLE cuenta
    ADD CONSTRAINT cuenta_estado_ck
        CHECK (estado IN ('ACTIVA', 'PENDIENTE', 'INACTIVA')),
    ADD CONSTRAINT cuenta_rol_estado_ck
        CHECK (
            (rol = 'DUENO' AND estado IN ('ACTIVA', 'INACTIVA'))
            OR (rol = 'OPERADOR' AND estado IN ('PENDIENTE', 'ACTIVA', 'INACTIVA'))
        ),
    ADD CONSTRAINT cuenta_estado_credencial_ck
        CHECK (
            (estado = 'ACTIVA' AND hash_contrasena_acceso IS NOT NULL)
            OR (estado IN ('PENDIENTE', 'INACTIVA') AND hash_contrasena_acceso IS NULL)
        );

DROP INDEX cuenta_correo_activa_uq;
CREATE UNIQUE INDEX cuenta_correo_reservada_uq
    ON cuenta (correo_normalizado)
    WHERE estado IN ('ACTIVA', 'PENDIENTE');

CREATE TABLE invitacion_operador (
    operador_id UUID PRIMARY KEY REFERENCES cuenta(id) ON DELETE RESTRICT,
    token_hash CHAR(64) NOT NULL UNIQUE,
    generado_en TIMESTAMPTZ NOT NULL,
    vence_en TIMESTAMPTZ NOT NULL,
    consumido_en TIMESTAMPTZ,
    estado_envio VARCHAR(16) NOT NULL,
    intento_iniciado_en TIMESTAMPTZ NOT NULL,
    reemision_usada BOOLEAN NOT NULL DEFAULT FALSE,
    clave_reemision_hash CHAR(64),
    CONSTRAINT invitacion_operador_token_hash_ck
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT invitacion_operador_vigencia_ck
        CHECK (vence_en = generado_en + INTERVAL '2 hours'),
    CONSTRAINT invitacion_operador_consumo_ck
        CHECK (consumido_en IS NULL OR consumido_en >= generado_en),
    CONSTRAINT invitacion_operador_estado_envio_ck
        CHECK (estado_envio IN ('ENVIANDO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO', 'DESHABILITADO')),
    CONSTRAINT invitacion_operador_reemision_ck
        CHECK (
            (reemision_usada = FALSE AND clave_reemision_hash IS NULL)
            OR (
                reemision_usada = TRUE
                AND clave_reemision_hash IS NOT NULL
                AND clave_reemision_hash ~ '^[0-9a-f]{64}$'
            )
        )
);

CREATE TABLE idempotencia_registro_operador (
    dueno_cuenta_id UUID NOT NULL REFERENCES cuenta(id) ON DELETE RESTRICT,
    clave_hash CHAR(64) NOT NULL,
    huella_solicitud CHAR(64) NOT NULL,
    estado VARCHAR(10) NOT NULL,
    operador_id UUID UNIQUE REFERENCES cuenta(id) ON DELETE RESTRICT,
    creada_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT idempotencia_registro_operador_pk PRIMARY KEY (dueno_cuenta_id, clave_hash),
    CONSTRAINT idempotencia_registro_operador_clave_hash_ck
        CHECK (clave_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_registro_operador_huella_ck
        CHECK (huella_solicitud ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_registro_operador_estado_ck
        CHECK (
            (estado = 'RESERVADA' AND operador_id IS NULL)
            OR (estado = 'COMPLETADA' AND operador_id IS NOT NULL)
        )
);
