CREATE TABLE cuenta (
    id UUID PRIMARY KEY,
    nombres VARCHAR(120) NOT NULL,
    apellido_paterno VARCHAR(80) NOT NULL,
    apellido_materno VARCHAR(80),
    correo VARCHAR(254) NOT NULL,
    correo_normalizado VARCHAR(254) NOT NULL,
    rol VARCHAR(16) NOT NULL CHECK (rol IN ('DUENO', 'OPERADOR')),
    estado VARCHAR(16) NOT NULL CHECK (estado IN ('ACTIVA', 'INACTIVA')),
    hash_contrasena_acceso VARCHAR(512),
    revision_acceso BIGINT NOT NULL CHECK (revision_acceso >= 0),
    creada_en TIMESTAMPTZ NOT NULL,
    actualizada_en TIMESTAMPTZ NOT NULL,
    CONSTRAINT cuenta_estado_credencial_ck CHECK (
        (estado = 'ACTIVA' AND hash_contrasena_acceso IS NOT NULL)
        OR (estado = 'INACTIVA' AND hash_contrasena_acceso IS NULL)
    )
);

CREATE UNIQUE INDEX cuenta_correo_activa_uq
    ON cuenta (correo_normalizado) WHERE estado = 'ACTIVA';
CREATE UNIQUE INDEX cuenta_un_dueno_activo_uq
    ON cuenta (rol) WHERE estado = 'ACTIVA' AND rol = 'DUENO';

ALTER TABLE configuracion_estacionamiento
    ADD COLUMN dueno_cuenta_id UUID;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM configuracion_estacionamiento
        WHERE estado = 'CONFIGURADA'
          AND (correo_propietario IS NULL
               OR correo_propietario <> lower(trim(correo_propietario))
               OR hash_contrasena_acceso IS NULL)
    ) THEN
        RAISE EXCEPTION 'La identidad del dueño configurado requiere revisión de compatibilidad antes de migrar';
    END IF;
END $$;

INSERT INTO cuenta (
    id, nombres, apellido_paterno, apellido_materno, correo, correo_normalizado,
    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en
)
SELECT gen_random_uuid(), propietario_nombres, propietario_apellido_paterno,
       propietario_apellido_materno, correo_propietario,
       lower(trim(correo_propietario)), 'DUENO', 'ACTIVA', hash_contrasena_acceso,
       1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
FROM configuracion_estacionamiento
WHERE id = 1 AND estado = 'CONFIGURADA';

UPDATE configuracion_estacionamiento c
SET dueno_cuenta_id = a.id
FROM cuenta a
WHERE c.id = 1 AND c.estado = 'CONFIGURADA'
  AND a.rol = 'DUENO' AND a.estado = 'ACTIVA'
  AND a.correo_normalizado = lower(trim(c.correo_propietario));

ALTER TABLE configuracion_estacionamiento
    ADD CONSTRAINT configuracion_dueno_cuenta_fk
        FOREIGN KEY (dueno_cuenta_id) REFERENCES cuenta(id) ON DELETE RESTRICT,
    ADD CONSTRAINT configuracion_dueno_cuenta_uq UNIQUE (dueno_cuenta_id);

ALTER TABLE configuracion_estacionamiento
    DROP CONSTRAINT configuracion_estado_campos_ck;

UPDATE configuracion_estacionamiento
SET propietario_nombres = NULL,
    propietario_apellido_paterno = NULL,
    propietario_apellido_materno = NULL,
    correo_propietario = NULL,
    hash_contrasena_acceso = NULL;

ALTER TABLE configuracion_estacionamiento
    ADD CONSTRAINT configuracion_estado_campos_ck CHECK (
        (
            estado = 'SIN_CONFIGURAR'
            AND estacionamiento_id IS NULL
            AND dueno_cuenta_id IS NULL
            AND propietario_nombres IS NULL
            AND propietario_apellido_paterno IS NULL
            AND propietario_apellido_materno IS NULL
            AND correo_propietario IS NULL
            AND hash_contrasena_acceso IS NULL
            AND hash_contrasena_administrativa IS NULL
            AND nombre_estacionamiento IS NULL
            AND tipo_estacionamiento IS NULL
            AND modo_horario IS NULL
            AND zona_horaria IS NULL
            AND hora_apertura IS NULL
            AND hora_cierre IS NULL
            AND transfer_id IS NULL
            AND hash_grant_transferencia IS NULL
            AND grant_vence_en IS NULL
            AND hash_recuperacion_transferencia IS NULL
        )
        OR
        (
            estado = 'CONFIGURADA'
            AND estacionamiento_id IS NOT NULL
            AND dueno_cuenta_id IS NOT NULL
            AND propietario_nombres IS NULL
            AND propietario_apellido_paterno IS NULL
            AND propietario_apellido_materno IS NULL
            AND correo_propietario IS NULL
            AND hash_contrasena_acceso IS NULL
            AND hash_contrasena_administrativa IS NOT NULL
            AND nombre_estacionamiento IS NOT NULL
            AND tipo_estacionamiento IS NOT NULL
            AND tipo_estacionamiento IN ('PUBLICO', 'PRIVADO', 'MIXTO')
            AND modo_horario IS NOT NULL
            AND modo_horario IN ('CONTINUO_24_7', 'INTERVALO_DIARIO')
            AND zona_horaria IS NOT NULL
            AND transfer_id IS NULL
            AND hash_grant_transferencia IS NULL
            AND grant_vence_en IS NULL
            AND hash_recuperacion_transferencia IS NULL
        )
        OR
        (
            estado = 'TRANSFERENCIA_PENDIENTE'
            AND estacionamiento_id IS NOT NULL
            AND dueno_cuenta_id IS NULL
            AND propietario_nombres IS NULL
            AND propietario_apellido_paterno IS NULL
            AND propietario_apellido_materno IS NULL
            AND correo_propietario IS NULL
            AND hash_contrasena_acceso IS NULL
            AND hash_contrasena_administrativa IS NULL
            AND nombre_estacionamiento IS NOT NULL
            AND tipo_estacionamiento IS NOT NULL
            AND tipo_estacionamiento IN ('PUBLICO', 'PRIVADO', 'MIXTO')
            AND modo_horario IS NOT NULL
            AND modo_horario IN ('CONTINUO_24_7', 'INTERVALO_DIARIO')
            AND zona_horaria IS NOT NULL
            AND transfer_id IS NOT NULL
            AND hash_grant_transferencia IS NOT NULL
            AND grant_vence_en IS NOT NULL
            AND hash_recuperacion_transferencia IS NOT NULL
        )
    );
