INSERT INTO idempotencia_accion_operador (
    operador_id, operacion, clave_hash, creada_en, estado_envio, revision_acceso, vence_en)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (operador_id, operacion, clave_hash) DO NOTHING
