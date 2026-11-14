INSERT INTO intento_checkout (
    intento_id, cliente_id, clave_hash, huella_solicitud, estado,
    price_id, livemode, creado_en, actualizado_en)
VALUES (?, ?, ?, ?, 'RESERVADO', ?, FALSE, ?, ?)
