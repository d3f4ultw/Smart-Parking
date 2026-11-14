INSERT INTO cliente_stripe (cliente_id, estado, livemode, creada_en, actualizada_en)
VALUES (?, 'RESERVADO', FALSE, ?, ?)
ON CONFLICT (cliente_id) DO NOTHING
