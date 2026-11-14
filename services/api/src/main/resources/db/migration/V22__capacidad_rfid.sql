-- Conserva todas las decisiones de V21 y agrega el rechazo por capacidad RFID2.
ALTER TABLE evento_acceso
    DROP CONSTRAINT evento_acceso_decision_ck,
    ADD CONSTRAINT evento_acceso_decision_ck CHECK (
        (resultado = 'AUTORIZADA'
            AND motivo IS NULL AND asociacion_id IS NOT NULL AND movimiento_id IS NOT NULL)
        OR
        (resultado = 'DENEGADA' AND movimiento_id IS NULL AND motivo IS NOT NULL
            AND (
                (lector = 'RFID2' AND (
                    (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
                    OR (motivo IN ('TARJETA_CANCELADA', 'ENTRADA_PENDIENTE', 'FUERA_DE_HORARIO',
                                   'CAPACIDAD_COMPLETA')
                        AND asociacion_id IS NOT NULL)
                ))
                OR
                (lector = 'RFID3' AND (
                    (motivo = 'TARJETA_DESCONOCIDA' AND asociacion_id IS NULL)
                    OR (motivo IN ('TARJETA_CANCELADA', 'SIN_ENTRADA_ABIERTA')
                        AND asociacion_id IS NOT NULL)
                ))
            ))
    );
