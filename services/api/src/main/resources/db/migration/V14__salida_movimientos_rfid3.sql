ALTER TABLE movimiento_estacionamiento
    ADD COLUMN lectura_salida_id UUID,
    ADD CONSTRAINT movimiento_estacionamiento_salida_lectura_uq
        UNIQUE (lectura_salida_id),
    ADD CONSTRAINT movimiento_estacionamiento_salida_lectura_ck
        CHECK (lectura_salida_id IS NULL OR instante_salida IS NOT NULL);
