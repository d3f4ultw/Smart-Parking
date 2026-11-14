CREATE TABLE configuracion_estacionamiento (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    estado VARCHAR(32) NOT NULL CHECK (estado IN ('SIN_CONFIGURAR', 'CONFIGURADA', 'TRANSFERENCIA_PENDIENTE')),
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
    revision_propietario BIGINT NOT NULL DEFAULT 0 CHECK (revision_propietario >= 0),
    estacionamiento_id UUID,
    propietario_nombres VARCHAR(120),
    propietario_apellido_paterno VARCHAR(80),
    propietario_apellido_materno VARCHAR(80),
    correo_propietario VARCHAR(254),
    hash_contrasena_acceso VARCHAR(512),
    hash_contrasena_administrativa VARCHAR(512),
    nombre_estacionamiento VARCHAR(120),
    tipo_estacionamiento VARCHAR(16),
    modo_horario VARCHAR(32),
    zona_horaria VARCHAR(80),
    hora_apertura TIME WITHOUT TIME ZONE,
    hora_cierre TIME WITHOUT TIME ZONE,
    transfer_id UUID,
    hash_grant_transferencia VARCHAR(128),
    grant_vence_en TIMESTAMP WITH TIME ZONE,
    hash_recuperacion_transferencia VARCHAR(512),
    estado_aviso_transferencia VARCHAR(24) NOT NULL DEFAULT 'NO_APLICA'
        CHECK (estado_aviso_transferencia IN ('NO_APLICA', 'RESERVADO', 'DESHABILITADO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO')),
    estado_aviso_bienvenida VARCHAR(24) NOT NULL DEFAULT 'NO_APLICA'
        CHECK (estado_aviso_bienvenida IN ('NO_APLICA', 'RESERVADO', 'DESHABILITADO', 'ENVIADO', 'FALLIDO', 'DESCONOCIDO')),
    ultima_operacion_id UUID,
    ultima_clave_idempotencia_hash VARCHAR(64),
    CONSTRAINT configuracion_estado_campos_ck CHECK (
        (
            estado = 'SIN_CONFIGURAR'
            AND estacionamiento_id IS NULL
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
            AND propietario_nombres IS NOT NULL
            AND propietario_apellido_paterno IS NOT NULL
            AND propietario_apellido_materno IS NOT NULL
            AND correo_propietario IS NOT NULL
            AND hash_contrasena_acceso IS NOT NULL
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
    ),
    CONSTRAINT configuracion_horario_ck CHECK (
        (modo_horario IS NULL AND hora_apertura IS NULL AND hora_cierre IS NULL)
        OR (modo_horario = 'CONTINUO_24_7' AND hora_apertura IS NULL AND hora_cierre IS NULL)
        OR (modo_horario = 'INTERVALO_DIARIO'
            AND hora_apertura IS NOT NULL
            AND hora_cierre IS NOT NULL
            AND hora_apertura <> hora_cierre)
    ),
    CONSTRAINT configuracion_idempotencia_ck CHECK (
        (ultima_operacion_id IS NULL AND ultima_clave_idempotencia_hash IS NULL)
        OR (ultima_operacion_id IS NOT NULL AND ultima_clave_idempotencia_hash IS NOT NULL)
    )
);

INSERT INTO configuracion_estacionamiento (id, estado, revision, revision_propietario)
VALUES (1, 'SIN_CONFIGURAR', 0, 0);
