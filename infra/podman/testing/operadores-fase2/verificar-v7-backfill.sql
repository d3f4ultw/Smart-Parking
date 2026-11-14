\getenv owner_email TEST_OWNER_EMAIL
\getenv owner_password TEST_OWNER_PASSWORD
SELECT EXISTS (
    SELECT 1 FROM cuenta
    WHERE id = '00000000-0000-4000-8000-000000000001'
      AND rol = 'DUENO' AND estado = 'ACTIVA'
      AND correo_normalizado = lower(trim(:'owner_email'))
) AS owner_preserved \gset
\if :owner_preserved
\else
\echo 'V7 no preservó el dueño sintético de la fixture.'
\quit 4
\endif
SELECT EXISTS (
    SELECT 1 FROM cuenta
    WHERE id = '00000000-0000-4000-8000-000000000001'
      AND crypt(:'owner_password', hash_contrasena_acceso) = hash_contrasena_acceso
) AS owner_hash_preserved \gset
\if :owner_hash_preserved
\else
\echo 'V7 no preservó la credencial del dueño sintético.'
\quit 4
\endif

DO $$
DECLARE
    ids UUID[] := ARRAY[
        '10000000-0000-4000-8000-000000000001'::UUID,
        '10000000-0000-4000-8000-000000000002'::UUID,
        '10000000-0000-4000-8000-000000000003'::UUID
    ];
BEGIN
    IF EXISTS (SELECT 1 FROM flyway_schema_history WHERE success = FALSE)
       OR NOT EXISTS (
           SELECT 1 FROM flyway_schema_history
           WHERE version = '7' AND success = TRUE
       ) THEN
        RAISE EXCEPTION 'Flyway no completó V7 de forma limpia.';
    END IF;
    IF (SELECT count(*) FROM flyway_schema_history WHERE version = '7' AND success = TRUE) <> 1 THEN
        RAISE EXCEPTION 'Flyway debe registrar V7 exactamente una vez.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM unnest(ARRAY['1', '2', '3', '4', '5', '6', '7']) esperada(version)
        WHERE NOT EXISTS (
            SELECT 1 FROM flyway_schema_history h
            WHERE h.version = esperada.version AND h.success = TRUE
        )
    ) THEN
        RAISE EXCEPTION 'La cadena V1-V7 no está completa.';
    END IF;
    IF (SELECT count(*) FROM cuenta WHERE id = ANY(ids)) <> 3
       OR NOT EXISTS (SELECT 1 FROM cuenta WHERE id = ids[1] AND estado = 'ACTIVA'
                      AND rol = 'OPERADOR' AND hash_contrasena_acceso IS NOT NULL)
       OR NOT EXISTS (SELECT 1 FROM cuenta WHERE id = ids[2] AND estado = 'PENDIENTE'
                      AND rol = 'OPERADOR' AND hash_contrasena_acceso IS NULL)
       OR NOT EXISTS (SELECT 1 FROM cuenta WHERE id = ids[3] AND estado = 'INACTIVA'
                      AND rol = 'OPERADOR' AND hash_contrasena_acceso IS NULL) THEN
        RAISE EXCEPTION 'V7 alteró las cuentas sintéticas o sus estados/credenciales.';
    END IF;
    IF (SELECT count(*) FROM invitacion_operador WHERE operador_id = ANY(ids)) <> 3
       OR (SELECT count(*) FROM idempotencia_registro_operador
           WHERE operador_id = ANY(ids) AND estado = 'COMPLETADA') <> 3 THEN
        RAISE EXCEPTION 'V7 no preservó invitaciones o claves de registro V6.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'invitacion_operador'
          AND column_name IN ('reemision_usada', 'clave_reemision_hash')
    ) THEN
        RAISE EXCEPTION 'V7 dejó activo el esquema de reemisión única de V6.';
    END IF;
    IF (SELECT count(*) FROM idempotencia_accion_operador
        WHERE operador_id = ANY(ids) AND operacion = 'REEMITIR_INVITACION') <> 1
       OR NOT EXISTS (
           SELECT 1
           FROM idempotencia_accion_operador a
           JOIN cuenta c ON c.id = a.operador_id
           JOIN invitacion_operador i ON i.operador_id = a.operador_id
           WHERE a.operador_id = ids[2]
             AND a.operacion = 'REEMITIR_INVITACION'
             AND a.clave_hash = encode(digest('fase2-v6-reemision-replay-2026', 'sha256'), 'hex')
             AND a.creada_en = i.generado_en
             AND a.estado_envio = i.estado_envio
             AND a.revision_acceso = c.revision_acceso
             AND a.vence_en = i.vence_en
       ) THEN
        RAISE EXCEPTION 'V7 no hizo backfill fiel de la reemisión histórica.';
    END IF;
    IF EXISTS (SELECT 1 FROM recuperacion_contrasena_operador WHERE operador_id = ANY(ids)) THEN
        RAISE EXCEPTION 'V7 creó recuperaciones no presentes en el origen V6.';
    END IF;
    IF (SELECT count(*) FROM pg_constraint
        WHERE conrelid = 'idempotencia_accion_operador'::regclass
          AND contype = 'c' AND convalidated) <> 4
       OR (SELECT count(*) FROM pg_constraint
           WHERE conrelid = 'recuperacion_contrasena_operador'::regclass
             AND contype = 'c' AND convalidated) <> 4
       OR (SELECT count(*) FROM pg_constraint
           WHERE conrelid IN ('idempotencia_accion_operador'::regclass,
                              'recuperacion_contrasena_operador'::regclass)
             AND contype = 'f' AND convalidated) <> 2 THEN
        RAISE EXCEPTION 'V7 dejó constraints CHECK o claves foráneas sin validar.';
    END IF;
    IF (SELECT count(*) FROM pg_index
        WHERE indexrelid IN ('idempotencia_accion_operador_invitaciones_idx'::regclass,
                             'idempotencia_accion_operador_recuperacion_idx'::regclass)
          AND indisvalid AND indisready) <> 2 THEN
        RAISE EXCEPTION 'V7 dejó inválido un índice de cuotas de acciones.';
    END IF;
END $$;

\echo 'V7_BACKFILL_OK: cuentas, invitaciones, registros e idempotencia histórica preservados.'
