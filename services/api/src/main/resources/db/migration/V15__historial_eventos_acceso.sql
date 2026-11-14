CREATE TABLE evento_acceso (
    evento_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocurrido_en TIMESTAMPTZ NOT NULL,
    lector VARCHAR NOT NULL,
    resultado VARCHAR NOT NULL,
    motivo VARCHAR,
    lectura_id UUID NOT NULL,
    asociacion_id BIGINT,
    movimiento_id BIGINT,
    CONSTRAINT evento_acceso_lector_ck CHECK (lector IN ('RFID2', 'RFID3')),
    CONSTRAINT evento_acceso_resultado_ck CHECK (resultado IN ('AUTORIZADA', 'DENEGADA')),
    CONSTRAINT evento_acceso_lectura_uq UNIQUE (lector, lectura_id),
    CONSTRAINT evento_acceso_asociacion_fk
        FOREIGN KEY (asociacion_id)
        REFERENCES asociacion_tarjeta_rfid1(asociacion_id) ON DELETE RESTRICT,
    CONSTRAINT evento_acceso_movimiento_fk
        FOREIGN KEY (movimiento_id)
        REFERENCES movimiento_estacionamiento(movimiento_id) ON DELETE RESTRICT,
    CONSTRAINT evento_acceso_decision_ck CHECK (
        (resultado = 'AUTORIZADA'
            AND motivo IS NULL AND asociacion_id IS NOT NULL AND movimiento_id IS NOT NULL)
        OR
        (resultado = 'DENEGADA' AND movimiento_id IS NULL AND motivo IS NOT NULL
            AND (
                (lector = 'RFID2' AND (
                    (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
                    OR (motivo IN ('TARJETA_CANCELADA', 'ENTRADA_PENDIENTE')
                        AND asociacion_id IS NOT NULL)
                ))
                OR
                (lector = 'RFID3' AND (
                    (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
                    OR (motivo IN ('TARJETA_CANCELADA', 'SIN_ENTRADA_ABIERTA')
                        AND asociacion_id IS NOT NULL)
                ))
            ))
    )
);

CREATE INDEX evento_acceso_cronologico_idx
    ON evento_acceso (ocurrido_en DESC, evento_id DESC);
