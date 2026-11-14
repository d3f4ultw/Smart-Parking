INSERT INTO cuenta (
    id, nombres, primer_apellido, segundo_apellido, correo,
    correo_normalizado, rol, estado, hash_contrasena_acceso,
    revision_acceso, creada_en, actualizada_en)
VALUES (?, ?, ?, ?, ?, ?, 'DUENO', 'ACTIVA', ?, 1, ?, ?)
