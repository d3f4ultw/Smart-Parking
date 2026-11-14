CREATE TABLE movimiento_estacionamiento (
    movimiento_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asociacion_id BIGINT NOT NULL,
    tipo_persona VARCHAR(9) NOT NULL,
    cliente_id UUID,
    empleado_id BIGINT,
    uid_historico VARCHAR(20) NOT NULL,
    lectura_id UUID NOT NULL,
    fecha_entrada DATE NOT NULL,
    hora_entrada TIME WITHOUT TIME ZONE NOT NULL,
    instante_entrada TIMESTAMPTZ NOT NULL,
    fecha_salida DATE,
    hora_salida TIME WITHOUT TIME ZONE,
    instante_salida TIMESTAMPTZ,
    CONSTRAINT movimiento_estacionamiento_asociacion_fk
        FOREIGN KEY (asociacion_id)
        REFERENCES asociacion_tarjeta_rfid1(asociacion_id) ON DELETE RESTRICT,
    CONSTRAINT movimiento_estacionamiento_cliente_fk
        FOREIGN KEY (cliente_id) REFERENCES cliente_codigo_publico(cliente_id) ON DELETE RESTRICT,
    CONSTRAINT movimiento_estacionamiento_empleado_fk
        FOREIGN KEY (empleado_id) REFERENCES empleado(id) ON DELETE RESTRICT,
    CONSTRAINT movimiento_estacionamiento_tipo_persona_ck CHECK (
        (tipo_persona = 'CLIENTE' AND cliente_id IS NOT NULL AND empleado_id IS NULL)
        OR (tipo_persona = 'EMPLEADO' AND cliente_id IS NULL AND empleado_id IS NOT NULL)
    ),
    CONSTRAINT movimiento_estacionamiento_uid_ck CHECK (
        uid_historico ~ '^[0-9A-F]{8}([0-9A-F]{6}|[0-9A-F]{12})?$'
    ),
    CONSTRAINT movimiento_estacionamiento_lectura_uq UNIQUE (lectura_id),
    CONSTRAINT movimiento_estacionamiento_salida_ck CHECK (
        (fecha_salida IS NULL AND hora_salida IS NULL AND instante_salida IS NULL)
        OR (fecha_salida IS NOT NULL AND hora_salida IS NOT NULL AND instante_salida IS NOT NULL
            AND instante_salida >= instante_entrada)
    )
);

CREATE UNIQUE INDEX movimiento_estacionamiento_entrada_abierta_uq
    ON movimiento_estacionamiento (asociacion_id)
    WHERE instante_salida IS NULL;
