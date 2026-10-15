-- Remove development accounts and operational history while retaining dynamic cajones.
-- This script is intentionally limited to the isolated sandbox and dev database.
DO $$
BEGIN
    IF current_database() NOT IN ('smart_parking_sandbox', 'smart_parking_dev') THEN
        RAISE EXCEPTION 'Refusing to purge database %.', current_database();
    END IF;

    TRUNCATE TABLE
        public.activaciones_cuenta,
        public.conexiones_sse_usuario,
        public.configuracion_estacionamiento,
        public.cuentas_propietario,
        public.desvinculaciones_propietario,
        public.historial_modalidad_estacionamiento,
        public.inscripciones_propietario,
        public.sesiones,
        public.sesiones_gestion_propietario,
        public.usuarios
    RESTART IDENTITY;

    DELETE FROM public.eventos_tiempo_real;
    DELETE FROM public.vision_requests;
    UPDATE public.vision_configuration
    SET current_session_id = NULL,
        last_heartbeat_at = NULL,
        last_observation_at = NULL,
        last_sequence = 0
    WHERE id = 1;

    RAISE NOTICE 'Development data purged; dynamic parking configuration and global SSE cursor remain.';
END;
$$;
