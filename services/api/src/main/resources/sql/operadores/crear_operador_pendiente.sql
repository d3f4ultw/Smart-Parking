INSERT INTO cuenta (
    id, nombres, primer_apellido, segundo_apellido, correo,
    correo_normalizado, rol, estado, hash_contrasena_acceso,
    revision_acceso, creada_en, actualizada_en)
VALUES (?, ?, ?, ?, ?, ?, 'OPERADOR', 'PENDIENTE', NULL, 0,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
