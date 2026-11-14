\getenv owner_email TEST_OWNER_EMAIL
\getenv owner_password TEST_OWNER_PASSWORD
SELECT (:'owner_email' ~ '^[^@]+@example[.]test$' AND char_length(:'owner_password') >= 10)
    AS fixture_credentials_valid \gset
\if :fixture_credentials_valid
\else
\echo 'La fixture requiere correo @example.test y contraseña sintética de al menos 10 caracteres.'
\quit 3
\endif

CREATE EXTENSION IF NOT EXISTS pgcrypto;
SELECT crypt(:'owner_password', gen_salt('bf', 12)) AS owner_hash \gset
SELECT encode(digest('fase2-v6-reemision-replay-2026', 'sha256'), 'hex') AS replay_key_hash \gset

BEGIN;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM cuenta
        WHERE id IN (
            '00000000-0000-4000-8000-000000000001',
            '10000000-0000-4000-8000-000000000001',
            '10000000-0000-4000-8000-000000000002',
            '10000000-0000-4000-8000-000000000003'
        )
    ) OR EXISTS (SELECT 1 FROM configuracion_estacionamiento WHERE estado <> 'SIN_CONFIGURAR') THEN
        RAISE EXCEPTION 'La base temporal ya contiene datos de fixture; usa un proyecto nuevo.';
    END IF;
END $$;

INSERT INTO cuenta (
    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en
) VALUES (
    '00000000-0000-4000-8000-000000000001', 'Dueño Fixture', 'Fase', 'Dos',
    lower(trim(:'owner_email')), lower(trim(:'owner_email')), 'DUENO', 'ACTIVA',
    :'owner_hash', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
);

UPDATE configuracion_estacionamiento
SET estado = 'CONFIGURADA',
    revision = 1,
    revision_propietario = 1,
    estacionamiento_id = '00000000-0000-4000-8000-000000000002',
    dueno_cuenta_id = '00000000-0000-4000-8000-000000000001',
    propietario_nombres = NULL,
    propietario_primer_apellido = NULL,
    propietario_segundo_apellido = NULL,
    correo_propietario = NULL,
    hash_contrasena_acceso = NULL,
    hash_contrasena_administrativa = :'owner_hash',
    nombre_estacionamiento = 'Fixture V6 desechable',
    tipo_estacionamiento = 'PUBLICO',
    modo_horario = 'CONTINUO_24_7',
    zona_horaria = 'America/Mexico_City',
    hora_apertura = NULL,
    hora_cierre = NULL,
    transfer_id = NULL,
    hash_grant_transferencia = NULL,
    grant_vence_en = NULL,
    hash_recuperacion_transferencia = NULL
WHERE id = 1 AND estado = 'SIN_CONFIGURAR';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM configuracion_estacionamiento
        WHERE id = 1 AND estado = 'CONFIGURADA'
          AND dueno_cuenta_id = '00000000-0000-4000-8000-000000000001'
    ) THEN
        RAISE EXCEPTION 'La fixture no pudo configurar al dueño sintético.';
    END IF;
END $$;

INSERT INTO cuenta (
    id, nombres, primer_apellido, segundo_apellido, correo, correo_normalizado,
    rol, estado, hash_contrasena_acceso, revision_acceso, creada_en, actualizada_en
) VALUES
    ('10000000-0000-4000-8000-000000000001', 'Operadora Activa', 'Fixture', 'Activa',
     'activa.v6@example.test', 'activa.v6@example.test', 'OPERADOR', 'ACTIVA',
     :'owner_hash', 7, CURRENT_TIMESTAMP - INTERVAL '4 hours', CURRENT_TIMESTAMP - INTERVAL '4 hours'),
    ('10000000-0000-4000-8000-000000000002', 'Operador Pendiente', 'Fixture', 'Reemitida',
     'pendiente.v6@example.test', 'pendiente.v6@example.test', 'OPERADOR', 'PENDIENTE',
     NULL, 4, CURRENT_TIMESTAMP - INTERVAL '5 minutes', CURRENT_TIMESTAMP - INTERVAL '5 minutes'),
    ('10000000-0000-4000-8000-000000000003', 'Operador Inactivo', 'Fixture', 'Inactivo',
     'inactivo.v6@example.test', 'inactivo.v6@example.test', 'OPERADOR', 'INACTIVA',
     NULL, 9, CURRENT_TIMESTAMP - INTERVAL '5 hours', CURRENT_TIMESTAMP - INTERVAL '5 hours');

INSERT INTO invitacion_operador (
    operador_id, token_hash, generado_en, vence_en, consumido_en, estado_envio,
    intento_iniciado_en, reemision_usada, clave_reemision_hash
) VALUES
    ('10000000-0000-4000-8000-000000000001', repeat('1', 64),
     CURRENT_TIMESTAMP - INTERVAL '4 hours', CURRENT_TIMESTAMP - INTERVAL '2 hours',
     CURRENT_TIMESTAMP - INTERVAL '3 hours 50 minutes', 'ENVIADO',
     CURRENT_TIMESTAMP - INTERVAL '4 hours', FALSE, NULL),
    ('10000000-0000-4000-8000-000000000002', repeat('2', 64),
     CURRENT_TIMESTAMP - INTERVAL '5 minutes', CURRENT_TIMESTAMP + INTERVAL '1 hour 55 minutes',
     NULL, 'ENVIADO', CURRENT_TIMESTAMP - INTERVAL '5 minutes', TRUE, :'replay_key_hash'),
    ('10000000-0000-4000-8000-000000000003', repeat('3', 64),
     CURRENT_TIMESTAMP - INTERVAL '5 hours', CURRENT_TIMESTAMP - INTERVAL '3 hours',
     NULL, 'DESHABILITADO', CURRENT_TIMESTAMP - INTERVAL '5 hours', FALSE, NULL);

INSERT INTO idempotencia_registro_operador (
    dueno_cuenta_id, clave_hash, huella_solicitud, estado, operador_id, creada_en
) VALUES
    ('00000000-0000-4000-8000-000000000001', repeat('a', 64), repeat('d', 64), 'COMPLETADA',
     '10000000-0000-4000-8000-000000000001', CURRENT_TIMESTAMP - INTERVAL '4 hours'),
    ('00000000-0000-4000-8000-000000000001', repeat('b', 64), repeat('e', 64), 'COMPLETADA',
     '10000000-0000-4000-8000-000000000002', CURRENT_TIMESTAMP - INTERVAL '5 minutes'),
    ('00000000-0000-4000-8000-000000000001', repeat('c', 64), repeat('9', 64), 'COMPLETADA',
     '10000000-0000-4000-8000-000000000003', CURRENT_TIMESTAMP - INTERVAL '5 hours');
COMMIT;

\echo 'Fixture V6 insertada; owner y operadores son sintéticos.'
