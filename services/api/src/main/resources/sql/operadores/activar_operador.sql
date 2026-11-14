UPDATE cuenta
SET estado = 'ACTIVA', hash_contrasena_acceso = ?,
    revision_acceso = revision_acceso + 1, actualizada_en = ?
WHERE id = ? AND rol = 'OPERADOR' AND estado = 'PENDIENTE'
  AND hash_contrasena_acceso IS NULL AND revision_acceso = ?
