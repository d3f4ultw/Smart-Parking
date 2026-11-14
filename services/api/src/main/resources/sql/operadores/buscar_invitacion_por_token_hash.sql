SELECT operador_id, token_hash, generado_en, vence_en, consumido_en,
       estado_envio, intento_iniciado_en
FROM invitacion_operador i
JOIN cuenta c ON c.id = i.operador_id
WHERE i.token_hash = ? AND i.consumido_en IS NULL
  AND c.rol = 'OPERADOR' AND c.estado = 'PENDIENTE'
  AND c.hash_contrasena_acceso IS NULL
