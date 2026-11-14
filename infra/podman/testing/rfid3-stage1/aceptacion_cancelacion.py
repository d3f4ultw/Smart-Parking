"""Fuerza ambos órdenes entre salida RFID3 y cancelación administrativa real."""

import concurrent.futures


def probar(entorno, sesion, csrf, tarjetas):
    for uid, cancela_primero in zip(tarjetas, (True, False)):
        entorno.exigir(entorno.autorizada(entorno.entrada(uid)), "entrada para cancelación administrativa")
        asociacion = entorno.sql(f"SELECT asociacion_id FROM asociacion_tarjeta_rfid1 WHERE uid_canonico='{uid}'")
        ruta = f"/api/v1/tarjetas-rfid/{asociacion}/cancelacion"

        def cancelar():
            return entorno.solicitud("POST", ruta, cliente=sesion, extra={"X-CSRF-TOKEN": csrf})

        def salir():
            return entorno.salida(uid)

        bloqueo = entorno.iniciar_bloqueo(uid)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as grupo:
                primero = grupo.submit(cancelar if cancela_primero else salir)
                entorno.esperar_bloqueo_api()
                segundo = grupo.submit(salir if cancela_primero else cancelar)
                r1, r2 = primero.result(timeout=7), segundo.result(timeout=7)
        finally:
            bloqueo.wait(timeout=5)
        cancelacion, salida = (r1, r2) if cancela_primero else (r2, r1)
        entorno.exigir(cancelacion[0] == 200 and cancelacion[1].get("estado") == "CANCELADA",
                       "ruta DUENO cancela la asociación sintética")
        if cancela_primero:
            entorno.exigir(entorno.denegada(salida, "TARJETA_CANCELADA"),
                           "cancelación real primero deniega salida")
            condicion = "instante_salida IS NULL"
        else:
            entorno.exigir(entorno.autorizada(salida), "salida primero confirma antes de cancelar")
            condicion = "instante_salida IS NOT NULL"
        entorno.exigir(entorno.sql(f"SELECT count(*) FROM movimiento_estacionamiento "
                                  f"WHERE asociacion_id={asociacion} AND {condicion}") == "1",
                       "el movimiento refleja el orden confirmado")
