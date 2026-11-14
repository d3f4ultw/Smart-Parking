SELECT huella_solicitud, operacion, empleado_id, estado, operador_id,
       estado_operador, revision_empleado, estado_envio
FROM idempotencia_accion_empleado_operador
WHERE dueno_cuenta_id = ? AND clave_hash = ?
FOR UPDATE
