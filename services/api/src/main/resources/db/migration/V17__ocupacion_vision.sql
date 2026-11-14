-- El estado de Vision es independiente de movimientos RFID y de sensores futuros.
-- La configuración es un singleton; el índice permite referenciar su UUID sin modificarlo.
CREATE UNIQUE INDEX configuracion_estacionamiento_id_vision_uq
    ON configuracion_estacionamiento(estacionamiento_id);

CREATE TABLE vision_fuente (
    fuente_id UUID PRIMARY KEY,
    estacionamiento_id UUID NOT NULL REFERENCES configuracion_estacionamiento(estacionamiento_id) ON DELETE RESTRICT,
    revision_calibracion BIGINT CHECK (revision_calibracion > 0),
    hash_calibracion CHAR(64),
    sesion_id UUID,
    sesion_iniciada_en TIMESTAMPTZ,
    calibracion_activada_en TIMESTAMPTZ,
    ultima_secuencia BIGINT NOT NULL DEFAULT 0 CHECK (ultima_secuencia >= 0),
    ultimo_observado_en TIMESTAMPTZ,
    CONSTRAINT vision_fuente_calibracion_ck CHECK (
        (revision_calibracion IS NULL AND hash_calibracion IS NULL)
        OR (revision_calibracion IS NOT NULL AND hash_calibracion ~ '^[0-9a-f]{64}$')
    )
);

CREATE TABLE vision_cajon (
    cajon_id UUID PRIMARY KEY,
    estacionamiento_id UUID NOT NULL REFERENCES configuracion_estacionamiento(estacionamiento_id) ON DELETE RESTRICT,
    etiqueta VARCHAR(100) NOT NULL
);

CREATE TABLE vision_zona (
    fuente_id UUID NOT NULL REFERENCES vision_fuente(fuente_id) ON DELETE RESTRICT,
    vision_zone_id UUID NOT NULL,
    cajon_id UUID NOT NULL REFERENCES vision_cajon(cajon_id) ON DELETE RESTRICT,
    activa BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (fuente_id, vision_zone_id)
);

-- Solo una fuente activa puede escribir el estado de Vision de un mismo cajón.
CREATE UNIQUE INDEX vision_zona_cajon_activo_uq ON vision_zona(cajon_id) WHERE activa;

CREATE TABLE vision_ocupacion (
    cajon_id UUID PRIMARY KEY REFERENCES vision_cajon(cajon_id) ON DELETE RESTRICT,
    fuente_id UUID NOT NULL REFERENCES vision_fuente(fuente_id) ON DELETE RESTRICT,
    sesion_id UUID NOT NULL,
    revision_calibracion BIGINT NOT NULL CHECK (revision_calibracion > 0),
    hash_calibracion CHAR(64) NOT NULL,
    ultimo_estado VARCHAR(7) NOT NULL CHECK (ultimo_estado IN ('LIBRE', 'OCUPADO')),
    observado_en TIMESTAMPTZ NOT NULL,
    recibido_en TIMESTAMPTZ NOT NULL
);

-- Recibos mínimos persistentes: evitan reutilizar IDs y no renuevan la frescura.
CREATE TABLE vision_solicitud (
    fuente_id UUID NOT NULL REFERENCES vision_fuente(fuente_id) ON DELETE RESTRICT,
    solicitud_id UUID NOT NULL,
    tipo VARCHAR(12) NOT NULL CHECK (tipo IN ('SESION', 'OBSERVACION')),
    hash_contenido CHAR(64) NOT NULL CHECK (hash_contenido ~ '^[0-9a-f]{64}$'),
    sesion_id UUID NOT NULL,
    creado_en TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fuente_id, solicitud_id)
);
