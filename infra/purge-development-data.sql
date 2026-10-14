-- Remove development accounts and operational history while retaining cajones.
-- This script is intentionally limited to the isolated sandbox and dev database.
DO $$
BEGIN
    IF current_database() NOT IN ('smart_parking_sandbox', 'smart_parking_dev') THEN
        RAISE EXCEPTION 'Refusing to purge database %.', current_database();
    END IF;

    IF (SELECT count(*) FROM public.cajones) <> 8 THEN
        RAISE EXCEPTION 'Expected exactly eight parking slots before purge.';
    END IF;

    TRUNCATE TABLE
        public.activaciones_cuenta,
        public.conexiones_sse_usuario,
        public.configuracion_estacionamiento,
        public.cuentas_propietario,
        public.desvinculaciones_propietario,
        public.estado_eventos_tiempo_real,
        public.eventos_tiempo_real,
        public.historial_modalidad_estacionamiento,
        public.inscripciones_propietario,
        public.sesiones,
        public.sesiones_gestion_propietario,
        public.usuarios
    RESTART IDENTITY;

    IF (SELECT count(*) FROM public.cajones) <> 8 THEN
        RAISE EXCEPTION 'Parking slot count changed during purge.';
    END IF;

    RAISE NOTICE 'Development data purged; all eight parking slots remain.';
END;
$$;
