ALTER TABLE asociacion_tarjeta_rfid1
    ADD COLUMN estado VARCHAR(10) NOT NULL DEFAULT 'ACTIVA',
    ADD COLUMN cancelada_en TIMESTAMPTZ,
    ADD CONSTRAINT asociacion_tarjeta_rfid1_estado_ck CHECK (
        (estado = 'ACTIVA' AND cancelada_en IS NULL)
        OR (estado = 'CANCELADA' AND cancelada_en IS NOT NULL)
    );

ALTER TABLE asociacion_tarjeta_rfid1
    DROP CONSTRAINT asociacion_tarjeta_rfid1_cliente_uq,
    DROP CONSTRAINT asociacion_tarjeta_rfid1_empleado_uq;

CREATE UNIQUE INDEX asociacion_tarjeta_rfid1_cliente_activa_uq
    ON asociacion_tarjeta_rfid1 (cliente_id)
    WHERE estado = 'ACTIVA' AND cliente_id IS NOT NULL;

CREATE UNIQUE INDEX asociacion_tarjeta_rfid1_empleado_activa_uq
    ON asociacion_tarjeta_rfid1 (empleado_id)
    WHERE estado = 'ACTIVA' AND empleado_id IS NOT NULL;

CREATE FUNCTION proteger_historial_asociacion_tarjeta_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'No se permite borrar el historial de tarjetas RFID.'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.estado = 'CANCELADA' THEN
        RAISE EXCEPTION 'Una tarjeta cancelada no puede modificarse.'
            USING ERRCODE = '23514';
    END IF;

    IF ROW(NEW.asociacion_id, NEW.uid_canonico, NEW.cliente_id, NEW.empleado_id, NEW.asociada_en)
            IS DISTINCT FROM ROW(OLD.asociacion_id, OLD.uid_canonico, OLD.cliente_id,
                OLD.empleado_id, OLD.asociada_en) THEN
        RAISE EXCEPTION 'La identidad y fecha original de una tarjeta son inmutables.'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.estado = OLD.estado AND NEW.estado = 'ACTIVA' AND NEW.cancelada_en IS NULL THEN
        RETURN NEW;
    END IF;

    IF OLD.estado = 'ACTIVA' AND NEW.estado = 'CANCELADA' AND NEW.cancelada_en IS NOT NULL THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'La única transición permitida es ACTIVA a CANCELADA.'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER asociacion_tarjeta_rfid1_historial_bud
BEFORE UPDATE OR DELETE ON asociacion_tarjeta_rfid1
FOR EACH ROW
EXECUTE FUNCTION proteger_historial_asociacion_tarjeta_rfid1();

CREATE FUNCTION prohibir_truncate_asociacion_tarjeta_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'No se permite truncar el historial de tarjetas RFID.'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER asociacion_tarjeta_rfid1_historial_truncate
BEFORE TRUNCATE ON asociacion_tarjeta_rfid1
FOR EACH STATEMENT
EXECUTE FUNCTION prohibir_truncate_asociacion_tarjeta_rfid1();

ALTER TABLE captura_rfid1
    ADD COLUMN huella_sesion CHAR(64),
    ADD COLUMN previsualizada_en TIMESTAMPTZ,
    ADD COLUMN confirmacion_vence_en TIMESTAMPTZ,
    ADD COLUMN hash_clave_confirmacion CHAR(64),
    ADD COLUMN codigo_confirmacion VARCHAR(32),
    ADD COLUMN asociacion_confirmada_id BIGINT
        REFERENCES asociacion_tarjeta_rfid1(asociacion_id) ON DELETE RESTRICT;

ALTER TABLE captura_rfid1
    ADD CONSTRAINT captura_rfid1_huella_sesion_ck CHECK (
        huella_sesion IS NULL OR huella_sesion ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT captura_rfid1_vista_previa_ck CHECK (
        (previsualizada_en IS NULL AND confirmacion_vence_en IS NULL)
        OR (previsualizada_en IS NOT NULL
            AND confirmacion_vence_en = previsualizada_en + INTERVAL '300 seconds')
    ),
    ADD CONSTRAINT captura_rfid1_confirmacion_ck CHECK (
        (hash_clave_confirmacion IS NULL AND codigo_confirmacion IS NULL
            AND asociacion_confirmada_id IS NULL)
        OR (hash_clave_confirmacion ~ '^[0-9a-f]{64}$'
            AND ((codigo_confirmacion IS NULL AND asociacion_confirmada_id IS NOT NULL)
                OR (codigo_confirmacion IN ('TARJETA_YA_REGISTRADA', 'PERSONA_CON_TARJETA')
                    AND asociacion_confirmada_id IS NULL)))
    );

CREATE FUNCTION validar_huella_sesion_captura_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.huella_sesion IS NULL OR NEW.huella_sesion !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Toda captura nueva requiere la huella SHA-256 de sesión.'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.huella_sesion IS DISTINCT FROM NEW.huella_sesion THEN
        RAISE EXCEPTION 'La huella de sesión de una captura es inmutable.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER captura_rfid1_validar_huella_sesion_biu
BEFORE INSERT OR UPDATE ON captura_rfid1
FOR EACH ROW
EXECUTE FUNCTION validar_huella_sesion_captura_rfid1();

ALTER TABLE captura_rfid1
    DROP CONSTRAINT captura_rfid1_estado_ck,
    ADD CONSTRAINT captura_rfid1_estado_ck CHECK (
        (estado IN ('PENDIENTE', 'ESCANEANDO') AND terminada_en IS NULL
            AND resultado IS NULL
            AND ((request_id IS NULL AND huella_uid IS NULL AND codigo_error IS NULL)
                OR (request_id IS NOT NULL AND huella_uid IS NOT NULL
                    AND codigo_error = 'TARJETA_YA_REGISTRADA')))
        OR
        (estado = 'VISTA_PREVIA' AND terminada_en IS NULL
            AND request_id IS NOT NULL AND huella_uid IS NOT NULL
            AND resultado = 'PREVIEW_READY' AND codigo_error IS NULL
            AND previsualizada_en IS NOT NULL AND confirmacion_vence_en IS NOT NULL)
        OR
        (estado = 'COMPLETADA' AND terminada_en IS NOT NULL
            AND request_id IS NOT NULL AND huella_uid IS NOT NULL
            AND resultado = 'ASOCIADA' AND codigo_error IS NULL
            AND ((hash_clave_confirmacion IS NULL AND asociacion_confirmada_id IS NULL)
                OR (hash_clave_confirmacion IS NOT NULL
                    AND asociacion_confirmada_id IS NOT NULL)))
        OR
        (estado = 'RECHAZADA' AND terminada_en IS NOT NULL
            AND request_id IS NOT NULL AND huella_uid IS NOT NULL
            AND resultado IS NULL AND codigo_error IN ('TARJETA_ASOCIADA', 'PERSONA_CON_TARJETA'))
        OR
        (estado IN ('CANCELADA', 'EXPIRADA') AND terminada_en IS NOT NULL
            AND resultado IS NULL
            AND (codigo_error IS NULL OR codigo_error = 'CAPTURA_NO_VIGENTE'))
    );

UPDATE captura_rfid1
SET estado = 'CANCELADA', resultado = NULL, codigo_error = 'CAPTURA_NO_VIGENTE',
    actualizada_en = CURRENT_TIMESTAMP, terminada_en = CURRENT_TIMESTAMP
WHERE estado IN ('PENDIENTE', 'ESCANEANDO') AND huella_sesion IS NULL;

DROP INDEX captura_rfid1_activa_uq;
CREATE UNIQUE INDEX captura_rfid1_activa_uq
    ON captura_rfid1 (lector)
    WHERE estado IN ('PENDIENTE', 'ESCANEANDO', 'VISTA_PREVIA');

DROP INDEX captura_rfid1_terminal_limpieza_idx;
CREATE INDEX captura_rfid1_terminal_limpieza_idx
    ON captura_rfid1 (actualizada_en)
    WHERE estado IN ('COMPLETADA', 'CANCELADA', 'EXPIRADA', 'RECHAZADA');

CREATE TABLE uid_temporal_rfid1 (
    captura_id CHAR(32) PRIMARY KEY,
    uid_canonico VARCHAR(20) NOT NULL,
    huella_uid CHAR(64) NOT NULL,
    previsualizada_en TIMESTAMPTZ NOT NULL,
    confirmacion_vence_en TIMESTAMPTZ NOT NULL,
    CONSTRAINT uid_temporal_rfid1_captura_fk FOREIGN KEY (captura_id)
        REFERENCES captura_rfid1(captura_id) ON DELETE CASCADE,
    CONSTRAINT uid_temporal_rfid1_uid_ck CHECK (
        uid_canonico ~ '^[0-9A-F]{8}([0-9A-F]{6}|[0-9A-F]{12})?$'
    ),
    CONSTRAINT uid_temporal_rfid1_huella_ck CHECK (huella_uid ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uid_temporal_rfid1_vigencia_ck CHECK (
        confirmacion_vence_en = previsualizada_en + INTERVAL '300 seconds'
    ),
    CONSTRAINT uid_temporal_rfid1_uid_uq UNIQUE (uid_canonico)
);

CREATE FUNCTION validar_uid_temporal_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM captura_rfid1
        WHERE captura_id = NEW.captura_id AND estado = 'VISTA_PREVIA'
          AND huella_uid = NEW.huella_uid
          AND previsualizada_en = NEW.previsualizada_en
          AND confirmacion_vence_en = NEW.confirmacion_vence_en
    ) THEN
        RAISE EXCEPTION 'El UID temporal requiere una captura en vista previa coincidente.'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM asociacion_tarjeta_rfid1 WHERE uid_canonico = NEW.uid_canonico
    ) THEN
        RAISE EXCEPTION 'Una UID histórica no puede almacenarse como vista previa.'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER uid_temporal_rfid1_validar_bi
BEFORE INSERT ON uid_temporal_rfid1
FOR EACH ROW
EXECUTE FUNCTION validar_uid_temporal_rfid1();

CREATE FUNCTION proteger_uid_temporal_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'El UID temporal no puede modificarse.'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER uid_temporal_rfid1_proteger_bu
BEFORE UPDATE ON uid_temporal_rfid1
FOR EACH ROW
EXECUTE FUNCTION proteger_uid_temporal_rfid1();

CREATE FUNCTION limpiar_uid_temporal_rfid1() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.estado = 'VISTA_PREVIA' AND NEW.estado <> 'VISTA_PREVIA' THEN
        DELETE FROM uid_temporal_rfid1 WHERE captura_id = NEW.captura_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER captura_rfid1_limpiar_uid_au
AFTER UPDATE OF estado ON captura_rfid1
FOR EACH ROW
EXECUTE FUNCTION limpiar_uid_temporal_rfid1();
