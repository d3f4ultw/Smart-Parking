SELECT huella_solicitud, estado, empleado_id
FROM idempotencia_registro_empleado
WHERE cuenta_id = ? AND clave_hash = ?
