SELECT EXISTS (
    SELECT 1 FROM cuenta
    WHERE correo_normalizado = ? AND estado IN ('ACTIVA', 'PENDIENTE')
      AND (?::uuid IS NULL OR id <> ?)
)
