-- Una solicitud representa exclusivamente una salida de una visita abierta.
CREATE TABLE solicitud_salida_manual (
    operacion_id UUID PRIMARY KEY,
    movimiento_id BIGINT NOT NULL REFERENCES movimiento_estacionamiento(movimiento_id) ON DELETE RESTRICT,
    solicitante_cuenta_id UUID NOT NULL REFERENCES cuenta(id) ON DELETE RESTRICT,
    solicitante_rol VARCHAR(16) NOT NULL CHECK (solicitante_rol IN ('DUENO', 'OPERADOR')),
    revision_acceso BIGINT NOT NULL,
    revision_propietario BIGINT NOT NULL,
    huella_sesion CHAR(64) NOT NULL CHECK (huella_sesion ~ '^[0-9a-f]{64}$'),
    estado VARCHAR(16) NOT NULL CHECK (estado IN
        ('PENDIENTE', 'EMITIDA', 'CONFIRMADA', 'NO_EJECUTADA', 'INCIERTA', 'ANULADA')),
    creada_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    vence_en TIMESTAMPTZ NOT NULL,
    emitida_en TIMESTAMPTZ,
    boot_id VARCHAR(22),
    ticket_id VARCHAR(22),
    resultado_en TIMESTAMPTZ,
    CONSTRAINT solicitud_salida_manual_datos_emision_ck CHECK (
        (emitida_en IS NULL AND boot_id IS NULL AND ticket_id IS NULL)
        OR (emitida_en IS NOT NULL AND boot_id IS NOT NULL AND ticket_id IS NOT NULL
            AND boot_id ~ '^[A-Za-z0-9_-]{22}$' AND ticket_id ~ '^[A-Za-z0-9_-]{22}$')
    ),
    CONSTRAINT solicitud_salida_manual_estado_emision_ck CHECK (
        (estado IN ('PENDIENTE', 'ANULADA') AND emitida_en IS NULL)
        OR (estado IN ('EMITIDA', 'INCIERTA', 'CONFIRMADA', 'NO_EJECUTADA') AND emitida_en IS NOT NULL)
    )
);
CREATE UNIQUE INDEX solicitud_salida_manual_activa_uq
    ON solicitud_salida_manual(movimiento_id)
    WHERE estado IN ('PENDIENTE', 'EMITIDA', 'INCIERTA');
CREATE INDEX solicitud_salida_manual_pendiente_idx ON solicitud_salida_manual(creada_en)
    WHERE estado IN ('PENDIENTE', 'EMITIDA', 'INCIERTA');

ALTER TABLE evento_acceso DROP CONSTRAINT evento_acceso_lector_ck;
ALTER TABLE evento_acceso ADD CONSTRAINT evento_acceso_lector_ck CHECK (lector IN ('RFID2', 'RFID3', 'MANUAL'));
ALTER TABLE evento_acceso DROP CONSTRAINT evento_acceso_decision_ck;
ALTER TABLE evento_acceso ADD CONSTRAINT evento_acceso_decision_ck CHECK (
    (resultado = 'AUTORIZADA' AND motivo IS NULL AND asociacion_id IS NOT NULL AND movimiento_id IS NOT NULL)
    OR
    (resultado = 'DENEGADA' AND movimiento_id IS NULL AND motivo IS NOT NULL AND (
        (lector = 'RFID2' AND (
            (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
            OR (motivo IN ('TARJETA_CANCELADA', 'ENTRADA_PENDIENTE', 'FUERA_DE_HORARIO',
                           'CAPACIDAD_COMPLETA', 'MEMBRESIA_NO_VIGENTE') AND asociacion_id IS NOT NULL)))
        OR
        (lector = 'RFID3' AND (
            (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
            OR (motivo IN ('TARJETA_CANCELADA', 'SIN_ENTRADA_ABIERTA', 'SALIDA_MANUAL_EN_CURSO')
                AND asociacion_id IS NOT NULL)))
    ))
);
