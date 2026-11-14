SELECT operacion, creada_en, estado_envio, revision_acceso, vence_en
FROM idempotencia_accion_operador
WHERE operador_id = ? AND operacion = ? AND clave_hash = ?
