INSERT INTO stripe_evento_procesado (
    event_id, event_type, object_id, estado, recibido_en,
    actualizado_en, livemode)
VALUES (?, ?, ?, 'RECIBIDO', ?, ?, FALSE)
ON CONFLICT (event_id) DO NOTHING
