SELECT uid_canonico, huella_uid, previsualizada_en, confirmacion_vence_en
FROM uid_temporal_rfid1 WHERE captura_id = ? FOR UPDATE
