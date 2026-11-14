SELECT estado, session_id FROM intento_checkout
WHERE intento_id = ? AND cliente_id = ? FOR UPDATE
