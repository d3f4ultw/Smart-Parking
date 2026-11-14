INSERT INTO idempotencia_accion_empleado_operador (
    dueno_cuenta_id, clave_hash, huella_solicitud, operacion, empleado_id, estado)
VALUES (?, ?, ?, ?, ?, 'RESERVADA')
ON CONFLICT (dueno_cuenta_id, clave_hash) DO NOTHING
