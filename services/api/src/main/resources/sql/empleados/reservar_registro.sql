INSERT INTO idempotencia_registro_empleado (
    cuenta_id, clave_hash, huella_solicitud, estado)
VALUES (?, ?, ?, 'RESERVADA')
ON CONFLICT (cuenta_id, clave_hash) DO NOTHING
