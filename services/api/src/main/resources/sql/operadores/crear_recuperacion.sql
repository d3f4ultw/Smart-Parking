INSERT INTO recuperacion_contrasena_operador (
    operador_id, token_hash, generado_en, vence_en, consumido_en,
    estado_envio, intento_iniciado_en)
VALUES (?, ?, ?, ?, NULL, 'ENVIANDO', ?)
ON CONFLICT (operador_id) DO UPDATE SET
    token_hash = EXCLUDED.token_hash, generado_en = EXCLUDED.generado_en,
    vence_en = EXCLUDED.vence_en, consumido_en = NULL,
    estado_envio = 'ENVIANDO', intento_iniciado_en = EXCLUDED.intento_iniciado_en
