SELECT count(*) FROM cuenta a
WHERE a.id = ? AND a.estado = 'ACTIVA' AND a.revision_acceso = ? AND a.rol = ?
  AND (a.rol <> 'OPERADOR' OR EXISTS (
      SELECT 1 FROM empleado e
      WHERE e.id = a.empleado_id AND e.estado = 'ACTIVO'))
  AND (? <> 'DUENO' OR EXISTS (
      SELECT 1 FROM configuracion_estacionamiento c
      WHERE c.id = 1 AND c.estado = 'CONFIGURADA'
        AND c.dueno_cuenta_id = a.id AND c.revision_propietario = ?))
