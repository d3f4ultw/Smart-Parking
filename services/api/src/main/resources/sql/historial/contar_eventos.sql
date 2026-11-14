SELECT count(*) FROM evento_acceso evento
WHERE (? = 'TODOS' OR evento.lector = ?)
    AND (? = 'TODOS' OR evento.resultado = ?)
    AND (CAST(? AS timestamptz) IS NULL OR evento.ocurrido_en >= CAST(? AS timestamptz))
    AND (CAST(? AS timestamptz) IS NULL OR evento.ocurrido_en < CAST(? AS timestamptz))
