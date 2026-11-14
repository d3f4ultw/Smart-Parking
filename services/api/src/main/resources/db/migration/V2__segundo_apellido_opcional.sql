ALTER TABLE configuracion_estacionamiento
    DROP CONSTRAINT configuracion_estado_campos_ck;

ALTER TABLE configuracion_estacionamiento
    ADD CONSTRAINT configuracion_estado_campos_ck CHECK (
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
    );
