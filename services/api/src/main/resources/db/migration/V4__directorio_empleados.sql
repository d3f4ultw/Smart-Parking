CREATE TABLE empleado (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombres VARCHAR(100) NOT NULL,
    primer_apellido VARCHAR(100) NOT NULL,
    segundo_apellido VARCHAR(100),
    estado VARCHAR(9) NOT NULL DEFAULT 'ACTIVO',
    revision BIGINT NOT NULL DEFAULT 1,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT empleado_nombres_no_vacios_ck CHECK (length(btrim(nombres)) > 0),
    CONSTRAINT empleado_primer_apellido_no_vacio_ck CHECK (length(btrim(primer_apellido)) > 0),
    CONSTRAINT empleado_estado_ck CHECK (estado IN ('ACTIVO', 'INACTIVO')),
    CONSTRAINT empleado_revision_ck CHECK (revision >= 1)
);

CREATE TABLE idempotencia_registro_empleado (
    cuenta_id UUID NOT NULL REFERENCES cuenta(id) ON DELETE RESTRICT,
    clave_hash CHAR(64) NOT NULL,
    huella_solicitud CHAR(64) NOT NULL,
    estado VARCHAR(10) NOT NULL,
    empleado_id BIGINT REFERENCES empleado(id) ON DELETE RESTRICT,
    creada_en TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT idempotencia_registro_empleado_pk PRIMARY KEY (cuenta_id, clave_hash),
    CONSTRAINT idempotencia_registro_empleado_clave_hash_ck CHECK (clave_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_registro_empleado_huella_ck CHECK (huella_solicitud ~ '^[0-9a-f]{64}$'),
    CONSTRAINT idempotencia_registro_empleado_estado_ck CHECK (
        (estado = 'RESERVADA' AND empleado_id IS NULL)
        OR (estado = 'COMPLETADA' AND empleado_id IS NOT NULL)
    )
);
