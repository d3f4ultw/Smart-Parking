UPDATE cuenta
SET estado = 'INACTIVA', hash_contrasena_acceso = NULL,
    revision_acceso = revision_acceso + 1, actualizada_en = ?
WHERE id = ? AND estado = 'ACTIVA'
