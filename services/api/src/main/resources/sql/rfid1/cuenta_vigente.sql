SELECT cuenta.id
FROM cuenta
JOIN configuracion_estacionamiento AS configuracion
  ON configuracion.id = 1 AND configuracion.estado = 'CONFIGURADA'
WHERE cuenta.id = ? AND cuenta.estado = 'ACTIVA'
  AND cuenta.revision_acceso = ?
  AND (
      (cuenta.rol = 'DUENO' AND configuracion.dueno_cuenta_id = cuenta.id
       AND configuracion.revision_propietario = ?)
      OR (cuenta.rol = 'OPERADOR' AND EXISTS (
          SELECT 1 FROM empleado empleado_actual
          WHERE empleado_actual.id = cuenta.empleado_id
            AND empleado_actual.estado = 'ACTIVO'))
  )
FOR UPDATE OF cuenta, configuracion
