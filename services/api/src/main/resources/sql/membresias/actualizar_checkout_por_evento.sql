UPDATE intento_checkout SET estado = ?, session_id = ?, actualizado_en = ?
WHERE intento_id = ? AND cliente_id = ? AND (session_id IS NULL OR session_id = ?)
  AND estado IN ('RESERVADO', 'ABIERTO', 'RECONCILIANDO', 'INDETERMINADO', 'FALLIDO')
