SELECT event_type, object_id, estado FROM stripe_evento_procesado WHERE event_id = ? FOR UPDATE
