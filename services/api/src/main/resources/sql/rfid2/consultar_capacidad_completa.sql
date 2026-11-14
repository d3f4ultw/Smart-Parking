SELECT (SELECT count(*) FROM movimiento_estacionamiento WHERE instante_salida IS NULL)
       >= (SELECT count(*) FROM vision_cajon c
           JOIN vision_zona z ON z.cajon_id = c.cajon_id AND z.activa
           WHERE c.estacionamiento_id = ?)
