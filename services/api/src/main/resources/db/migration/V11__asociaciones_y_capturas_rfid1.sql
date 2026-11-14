CREATE TABLE asociacion_tarjeta_rfid1 (
    asociacion_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    uid_canonico VARCHAR(20) NOT NULL,
    cliente_id UUID,
    empleado_id BIGINT,
    asociada_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT asociacion_tarjeta_rfid1_uid_ck
        CHECK (uid_canonico ~ '^[0-9A-F]{8}([0-9A-F]{6}|[0-9A-F]{12})?$'),
    CONSTRAINT asociacion_tarjeta_rfid1_destino_ck
        CHECK (
            (cliente_id IS NOT NULL AND empleado_id IS NULL)
            OR (cliente_id IS NULL AND empleado_id IS NOT NULL)
        ),
    CONSTRAINT asociacion_tarjeta_rfid1_uid_uq UNIQUE (uid_canonico),
    CONSTRAINT asociacion_tarjeta_rfid1_cliente_uq UNIQUE (cliente_id),
    CONSTRAINT asociacion_tarjeta_rfid1_empleado_uq UNIQUE (empleado_id),
    CONSTRAINT asociacion_tarjeta_rfid1_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cliente_codigo_publico(cliente_id) ON DELETE RESTRICT,
    CONSTRAINT asociacion_tarjeta_rfid1_empleado_fk
        FOREIGN KEY (empleado_id) REFERENCES empleado(id) ON DELETE RESTRICT
);

CREATE TABLE captura_rfid1 (
    captura_id CHAR(32) PRIMARY KEY,
    lector VARCHAR(8) NOT NULL DEFAULT 'RFID1',
    tipo_entidad VARCHAR(9) NOT NULL,
    codigo_persona VARCHAR(32) NOT NULL,
    cliente_id UUID,
    empleado_id BIGINT,
    propietario_cuenta_id UUID NOT NULL,
    revision_acceso BIGINT NOT NULL,
    revision_propietario BIGINT NOT NULL,
    clave_inicio_hash CHAR(64) NOT NULL,
    huella_solicitud CHAR(64) NOT NULL,
    request_id CHAR(4),
    huella_uid CHAR(64),
    estado VARCHAR(12) NOT NULL,
    resultado VARCHAR(16),
    codigo_error VARCHAR(32),
    creada_en TIMESTAMPTZ NOT NULL,
    actualizada_en TIMESTAMPTZ NOT NULL,
    vence_en TIMESTAMPTZ NOT NULL,
    terminada_en TIMESTAMPTZ,
    CONSTRAINT captura_rfid1_id_ck CHECK (captura_id ~ '^[0-9a-f]{32}$'),
    CONSTRAINT captura_rfid1_lector_ck CHECK (lector = 'RFID1'),
    CONSTRAINT captura_rfid1_destino_ck CHECK (
        (tipo_entidad = 'CLIENTE' AND cliente_id IS NOT NULL AND empleado_id IS NULL
            AND codigo_persona ~ '^CLI-[0-9]{4,}$')
        OR
        (tipo_entidad = 'EMPLEADO' AND cliente_id IS NULL AND empleado_id IS NOT NULL
            AND codigo_persona ~ '^E-[0-9]{4,}$')
    ),
    CONSTRAINT captura_rfid1_propietario_fk
        FOREIGN KEY (propietario_cuenta_id) REFERENCES cuenta(id) ON DELETE RESTRICT,
    CONSTRAINT captura_rfid1_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cliente_codigo_publico(cliente_id) ON DELETE RESTRICT,
    CONSTRAINT captura_rfid1_empleado_fk
        FOREIGN KEY (empleado_id) REFERENCES empleado(id) ON DELETE RESTRICT,
    CONSTRAINT captura_rfid1_revisiones_ck
        CHECK (revision_acceso >= 1 AND revision_propietario >= 1),
    CONSTRAINT captura_rfid1_idempotencia_ck
        CHECK (clave_inicio_hash ~ '^[0-9a-f]{64}$' AND huella_solicitud ~ '^[0-9a-f]{64}$'),
    CONSTRAINT captura_rfid1_lectura_ck
        CHECK (
            (request_id IS NULL AND huella_uid IS NULL)
            OR (request_id IS NOT NULL AND huella_uid IS NOT NULL
                AND request_id ~ '^[0-9A-F]{4}$' AND huella_uid ~ '^[0-9a-f]{64}$')
        ),
    CONSTRAINT captura_rfid1_vigencia_ck
        CHECK (vence_en = creada_en + INTERVAL '120 seconds'),
    CONSTRAINT captura_rfid1_estado_ck CHECK (
        (estado IN ('PENDIENTE', 'ESCANEANDO') AND terminada_en IS NULL
            AND request_id IS NULL AND resultado IS NULL AND codigo_error IS NULL)
        OR
        (estado = 'COMPLETADA' AND terminada_en IS NOT NULL
            AND request_id IS NOT NULL AND resultado = 'ASOCIADA' AND codigo_error IS NULL)
        OR
        (estado = 'RECHAZADA' AND terminada_en IS NOT NULL
            AND request_id IS NOT NULL AND resultado IS NULL
            AND codigo_error IS NOT NULL
            AND codigo_error IN ('TARJETA_ASOCIADA', 'PERSONA_CON_TARJETA'))
        OR
        (estado IN ('CANCELADA', 'EXPIRADA') AND terminada_en IS NOT NULL
            AND resultado IS NULL
            AND (codigo_error IS NULL OR codigo_error = 'CAPTURA_NO_VIGENTE'))
    )
);

CREATE UNIQUE INDEX captura_rfid1_idempotencia_uq
    ON captura_rfid1 (propietario_cuenta_id, clave_inicio_hash);

CREATE UNIQUE INDEX captura_rfid1_activa_uq
    ON captura_rfid1 (lector)
    WHERE estado IN ('PENDIENTE', 'ESCANEANDO');

CREATE INDEX captura_rfid1_propietario_idx
    ON captura_rfid1 (propietario_cuenta_id, creada_en DESC);

CREATE INDEX captura_rfid1_terminal_limpieza_idx
    ON captura_rfid1 (actualizada_en)
    WHERE estado IN ('COMPLETADA', 'CANCELADA', 'EXPIRADA', 'RECHAZADA');
