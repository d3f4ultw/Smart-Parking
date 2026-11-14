SELECT huella_solicitud, estado, operador_id
FROM idempotencia_registro_operador
WHERE dueno_cuenta_id = ? AND clave_hash = ?
