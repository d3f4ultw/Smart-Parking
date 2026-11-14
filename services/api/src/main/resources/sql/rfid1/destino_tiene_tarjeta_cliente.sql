SELECT EXISTS (
    SELECT 1
    FROM asociacion_tarjeta_rfid1
    WHERE cliente_id = ? AND estado = 'ACTIVA'
)
