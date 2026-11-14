SELECT r.operador_id, r.token_hash, r.generado_en, r.vence_en, r.consumido_en,
       r.estado_envio, r.intento_iniciado_en
FROM recuperacion_contrasena_operador r
JOIN cuenta c ON c.id = r.operador_id
WHERE r.token_hash = ? AND r.consumido_en IS NULL
  AND c.rol = 'OPERADOR' AND c.estado = 'ACTIVA'
  AND c.hash_contrasena_acceso IS NOT NULL
