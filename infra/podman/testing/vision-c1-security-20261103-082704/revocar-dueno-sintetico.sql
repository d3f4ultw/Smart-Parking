BEGIN;

DO $revocar_dueno_sintetico$
DECLARE
    cantidad_duenos_sinteticos INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO cantidad_duenos_sinteticos
      FROM cuenta
     WHERE rol = 'DUENO'
       AND estado = 'ACTIVA'
       AND correo_normalizado LIKE '%@example.test';

    IF cantidad_duenos_sinteticos <> 1 THEN
        RAISE EXCEPTION 'Se requiere exactamente un DUENO sintético activo.';
    END IF;

    UPDATE cuenta
       SET revision_acceso = revision_acceso + 1,
           actualizada_en = CURRENT_TIMESTAMP
     WHERE rol = 'DUENO'
       AND estado = 'ACTIVA'
       AND correo_normalizado LIKE '%@example.test'
       AND revision_acceso < 9223372036854775807;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No se pudo revocar el DUENO sintético.';
    END IF;
END;
$revocar_dueno_sintetico$;

COMMIT;
