UPDATE invitacion_operador
SET token_hash = ?, generado_en = ?, vence_en = ?, consumido_en = NULL,
    estado_envio = 'ENVIANDO', intento_iniciado_en = ?
WHERE operador_id = ?
