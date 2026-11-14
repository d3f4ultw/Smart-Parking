UPDATE intento_checkout
SET estado = ?, session_id = ?, expira_en = ?, actualizado_en = ?
WHERE intento_id = ? AND cliente_id = ?
