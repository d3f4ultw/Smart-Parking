-- Acota el coste de localizar recibos vencidos de una fuente sin modificar V17.
CREATE INDEX vision_solicitud_fuente_creado_idx
    ON vision_solicitud(fuente_id, creado_en, solicitud_id);
