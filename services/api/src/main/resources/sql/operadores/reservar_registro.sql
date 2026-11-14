INSERT INTO idempotencia_registro_operador (
    dueno_cuenta_id, clave_hash, huella_solicitud, estado)
VALUES (?, ?, ?, 'RESERVADA')
ON CONFLICT (dueno_cuenta_id, clave_hash) DO NOTHING
