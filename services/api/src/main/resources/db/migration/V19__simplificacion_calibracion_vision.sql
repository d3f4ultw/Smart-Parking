ALTER TABLE vision_ocupacion
    ALTER COLUMN revision_calibracion DROP NOT NULL,
    ALTER COLUMN hash_calibracion DROP NOT NULL;

ALTER TABLE vision_solicitud
    ALTER COLUMN hash_contenido DROP NOT NULL;
