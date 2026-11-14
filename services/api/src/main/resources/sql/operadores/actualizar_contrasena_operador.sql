UPDATE cuenta SET hash_contrasena_acceso = ?, revision_acceso = revision_acceso + 1,
    actualizada_en = ?
WHERE id = ? AND rol = 'OPERADOR' AND estado = 'ACTIVA'
  AND hash_contrasena_acceso IS NOT NULL AND revision_acceso = ?
