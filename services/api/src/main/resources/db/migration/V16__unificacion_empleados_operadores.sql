ALTER TABLE empleado
    ADD COLUMN correo VARCHAR(254),
    ADD COLUMN correo_normalizado VARCHAR(254),
    ADD COLUMN correo_fk_valor TEXT
        GENERATED ALWAYS AS (COALESCE(correo, '')) STORED,
    ADD COLUMN correo_normalizado_fk_valor TEXT
        GENERATED ALWAYS AS (COALESCE(correo_normalizado, '')) STORED,
    ADD CONSTRAINT empleado_correo_par_ck CHECK (
        (correo IS NULL AND correo_normalizado IS NULL)
        OR (
            correo IS NOT NULL
            AND correo_normalizado IS NOT NULL
            AND btrim(correo) <> ''
            AND correo = btrim(correo)
            AND correo_normalizado = lower(btrim(correo))
            AND correo_normalizado <> ''
        )
    );

ALTER TABLE empleado
    ADD CONSTRAINT empleado_id_correo_vinculo_uq
        UNIQUE (id, correo_fk_valor, correo_normalizado_fk_valor),
    ADD CONSTRAINT empleado_id_estado_vinculo_uq
        UNIQUE (id, estado);

ALTER TABLE cuenta
    ADD COLUMN empleado_id BIGINT,
    ADD COLUMN correo_fk_valor TEXT
        GENERATED ALWAYS AS (COALESCE(correo, '')) STORED,
    ADD COLUMN correo_normalizado_fk_valor TEXT
        GENERATED ALWAYS AS (COALESCE(correo_normalizado, '')) STORED,
    ADD COLUMN empleado_estado_fk_valor VARCHAR(9)
        GENERATED ALWAYS AS (
            CASE WHEN estado IN ('ACTIVA', 'PENDIENTE') THEN 'ACTIVO' ELSE NULL END
        ) STORED;

ALTER TABLE cuenta
    ALTER COLUMN correo DROP NOT NULL,
    ALTER COLUMN correo_normalizado DROP NOT NULL,
    ALTER COLUMN primer_apellido TYPE VARCHAR(100),
    ALTER COLUMN segundo_apellido TYPE VARCHAR(100);

ALTER TABLE cuenta
    ADD CONSTRAINT cuenta_correo_par_ck CHECK (
        (correo IS NULL AND correo_normalizado IS NULL)
        OR (
            correo IS NOT NULL
            AND correo_normalizado IS NOT NULL
            AND btrim(correo) <> ''
            AND correo_normalizado = lower(btrim(correo))
            AND correo_normalizado <> ''
        )
    ),
    ADD CONSTRAINT cuenta_correo_nulo_solo_operador_inactivo_ck CHECK (
        correo IS NOT NULL
        OR (rol = 'OPERADOR' AND estado = 'INACTIVA' AND empleado_id IS NOT NULL)
    ),
    ADD CONSTRAINT cuenta_empleado_solo_operador_ck CHECK (
        empleado_id IS NULL OR rol = 'OPERADOR'
    ),
    ADD CONSTRAINT cuenta_empleado_id_fk
        FOREIGN KEY (empleado_id) REFERENCES empleado(id) ON DELETE RESTRICT,
    ADD CONSTRAINT cuenta_empleado_id_uq UNIQUE (empleado_id),
    ADD CONSTRAINT cuenta_empleado_correo_fk
        FOREIGN KEY (empleado_id, correo_fk_valor, correo_normalizado_fk_valor)
        REFERENCES empleado (id, correo_fk_valor, correo_normalizado_fk_valor)
        ON UPDATE NO ACTION ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT cuenta_empleado_estado_fk
        FOREIGN KEY (empleado_id, empleado_estado_fk_valor)
        REFERENCES empleado (id, estado)
        ON UPDATE NO ACTION ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE idempotencia_accion_operador
    DROP CONSTRAINT idempotencia_accion_operador_operacion_ck,
    ADD CONSTRAINT idempotencia_accion_operador_operacion_ck
        CHECK (operacion IN (
            'REEMITIR_INVITACION', 'REACTIVAR', 'SOLICITAR_RECUPERACION', 'CAMBIAR_CORREO'
        ));

DROP INDEX idempotencia_accion_operador_invitaciones_idx;
CREATE INDEX idempotencia_accion_operador_invitaciones_idx
    ON idempotencia_accion_operador (operador_id, creada_en)
    WHERE operacion IN ('REEMITIR_INVITACION', 'REACTIVAR', 'CAMBIAR_CORREO');

CREATE TABLE idempotencia_accion_empleado_operador (
    dueno_cuenta_id UUID NOT NULL REFERENCES cuenta(id) ON DELETE RESTRICT,
    clave_hash CHAR(64) NOT NULL,
    huella_solicitud CHAR(64) NOT NULL,
    operacion VARCHAR(32) NOT NULL,
    empleado_id BIGINT NOT NULL REFERENCES empleado(id) ON DELETE RESTRICT,
    estado VARCHAR(10) NOT NULL,
    operador_id UUID REFERENCES cuenta(id) ON DELETE RESTRICT,
    estado_operador VARCHAR(10),
    revision_empleado BIGINT,
    estado_envio VARCHAR(16),
    creada_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT idempotencia_accion_empleado_operador_pk
        PRIMARY KEY (dueno_cuenta_id, clave_hash),
    CONSTRAINT idempotencia_accion_empleado_operador_hash_ck
        CHECK (clave_hash ~ '^[0-9a-f]{64}$' AND huella_solicitud ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_accion_empleado_operador_operacion_ck
        CHECK (operacion IN ('PROMOVER', 'CAMBIAR_CORREO', 'DESACTIVAR', 'VINCULAR')),
    CONSTRAINT idempotencia_accion_empleado_operador_estado_ck CHECK (
        (estado = 'RESERVADA'
            AND operador_id IS NULL
            AND estado_operador IS NULL
            AND revision_empleado IS NULL
            AND estado_envio IS NULL)
        OR
        (estado = 'COMPLETADA'
            AND revision_empleado >= 1
            AND (
                (operador_id IS NULL AND estado_operador IS NULL)
                OR (operador_id IS NOT NULL AND estado_operador IN ('PENDIENTE', 'ACTIVA', 'INACTIVA'))
            )
            AND (estado_envio IS NULL OR estado_envio IN (
                'ENVIANDO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO', 'DESHABILITADO'
            ))
        )
    )
);

CREATE INDEX idempotencia_accion_empleado_operador_empleado_idx
    ON idempotencia_accion_empleado_operador (empleado_id, creada_en);
