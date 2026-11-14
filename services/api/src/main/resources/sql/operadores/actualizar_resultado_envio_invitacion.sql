WITH actualizada AS (
    UPDATE invitacion_operador SET estado_envio = ?
    WHERE operador_id = ? AND token_hash = ? AND estado_envio = 'ENVIANDO'
      AND consumido_en IS NULL
    RETURNING estado_envio, consumido_en, vence_en
)
SELECT i.estado_envio, i.consumido_en, i.vence_en, CURRENT_TIMESTAMP AS ahora
FROM actualizada i
