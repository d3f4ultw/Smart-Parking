SELECT operador_id, token_hash, generado_en, vence_en, consumido_en,
       estado_envio, intento_iniciado_en
FROM invitacion_operador WHERE operador_id = ?
FOR UPDATE
