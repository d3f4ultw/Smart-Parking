UPDATE cuenta
SET estado = ?, hash_contrasena_acceso = NULL,
    revision_acceso = ?, actualizada_en = CURRENT_TIMESTAMP
WHERE id = ? AND rol = 'OPERADOR' AND revision_acceso = ?
