SELECT EXISTS (SELECT 1 FROM movimiento_estacionamiento
               WHERE instante_salida IS NULL
                 AND ((CAST(? AS uuid) IS NOT NULL AND cliente_id = CAST(? AS uuid))
                      OR (CAST(? AS bigint) IS NOT NULL AND empleado_id = CAST(? AS bigint))))
