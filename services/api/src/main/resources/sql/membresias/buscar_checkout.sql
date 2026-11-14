SELECT intento_id, cliente_id, estado, session_id, price_id, expira_en, creado_en
FROM intento_checkout WHERE cliente_id = ? AND intento_id = ?
