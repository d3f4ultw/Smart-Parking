SELECT a.* FROM configuracion_estacionamiento c
JOIN cuenta a ON a.id = c.dueno_cuenta_id
WHERE c.id = 1 AND c.estado = 'CONFIGURADA'
  AND a.estado = 'ACTIVA' AND a.rol = 'DUENO'
