"""Aceptación HTTP sintética contra la API RFID 1 Stage 2 aislada."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import uuid
from http_aceptacion import ClienteHttp, clave_idempotencia, clave_lectura, crear_captura, csrf, exigir, leer_tarjeta


UID_SINTETICOS: list[str] = []
SECRETOS_SINTETICOS: list[str] = []


def nuevo_uid() -> str:
    uid = secrets.token_hex(4).upper()
    UID_SINTETICOS.append(uid)
    return uid


def crear_propietario(base_url: str, sufijo: str):
    cliente = ClienteHttp(base_url)
    token = csrf(cliente)
    correo = os.environ.get("RFID1_STAGE2_OWNER_EMAIL", f"dueno-rfid-{sufijo}@example.invalid")
    contrasena = os.environ.get("RFID1_STAGE2_OWNER_PASSWORD", secrets.token_urlsafe(20))
    contrasena_admin = os.environ.get("RFID1_STAGE2_ADMIN_PASSWORD", secrets.token_urlsafe(20))
    SECRETOS_SINTETICOS.extend((contrasena, contrasena_admin))
    solicitud = {
        "propietario": {
            "nombres": "Prueba RFID",
            "primerApellido": "Sintetica",
            "segundoApellido": None,
            "correo": correo,
            "contrasenaAcceso": contrasena,
            "contrasenaAdministrativa": contrasena_admin,
        },
        "estacionamiento": {
            "nombre": "Validacion RFID aislada",
            "tipo": "PRIVADO",
            "horario": {
                "modo": "CONTINUO_24_7",
                "zonaHoraria": "America/Mexico_City",
                "horaApertura": None,
                "horaCierre": None,
            },
        },
    }
    respuesta = cliente.solicitar(
        "POST",
        "/api/v1/configuracion/inicial",
        solicitud,
        {"X-CSRF-TOKEN": token, "Idempotency-Key": clave_idempotencia()},
    )
    exigir(respuesta.estado == 201, "crear propietario sintético en API desechable")

    token = csrf(cliente)
    respuesta = cliente.solicitar(
        "POST",
        "/api/v1/sesion",
        {"correo": correo, "contrasena": contrasena},
        {"X-CSRF-TOKEN": token},
    )
    exigir(respuesta.estado == 200 and respuesta.json().get("autenticada") is True,
           "iniciar sesión DUENO sintética")
    token = respuesta.json().get("csrfToken")
    exigir(isinstance(token, str) and bool(token), "rotar token CSRF al iniciar sesión")
    return cliente, token


def crear_empleado(cliente: ClienteHttp, token_csrf: str, sufijo: str):
    respuesta = cliente.solicitar(
        "POST",
        "/api/v1/empleados",
        {"nombres": f"Empleado {sufijo}", "primerApellido": "Sintetico", "segundoApellido": None},
        {"X-CSRF-TOKEN": token_csrf, "Idempotency-Key": clave_idempotencia()},
    )
    exigir(respuesta.estado == 201, "crear empleado sintético")
    return respuesta.json()


def inactivar_empleado(cliente: ClienteHttp, token_csrf: str, empleado: dict) -> None:
    respuesta = cliente.solicitar(
        "PATCH",
        f"/api/v1/empleados/{empleado['id']}/estado",
        {"estado": "INACTIVO"},
        {"X-CSRF-TOKEN": token_csrf, "If-Match": '"1"'},
    )
    exigir(respuesta.estado == 200 and respuesta.json().get("estado") == "INACTIVO",
           "marcar empleado sintético INACTIVO")


def crear_cliente(cliente_dueno: ClienteHttp, token_csrf: str, base_url: str, sufijo: str) -> str:
    cliente_publico = ClienteHttp(base_url)
    token_cliente = csrf(cliente_publico, "/api/v1/clientes/csrf")
    contrasena_cliente = secrets.token_urlsafe(20)
    SECRETOS_SINTETICOS.append(contrasena_cliente)
    respuesta = cliente_publico.solicitar(
        "POST",
        "/api/v1/clientes/registro",
        {
            "nombres": f"Cliente {sufijo}",
            "primerApellido": "Sintetico",
            "segundoApellido": None,
            "correo": f"cliente-rfid-{sufijo}@example.invalid",
            "contrasena": contrasena_cliente,
        },
        {"X-CSRF-TOKEN": token_cliente},
    )
    exigir(respuesta.estado == 201, "crear cliente sintético por API")

    listado = cliente_dueno.solicitar("GET", "/api/v1/clientes/administracion?pagina=1")
    exigir(listado.estado == 200, "consultar directorio sintético de clientes")
    codigo = next(
        (item.get("codigo") for item in listado.json().get("items", [])
         if item.get("nombreCompleto") == f"Cliente {sufijo} Sintetico"),
        None,
    )
    exigir(isinstance(codigo, str) and codigo.startswith("CLI-"), "resolver código público de cliente")
    return codigo


def iniciar_y_leer(
    cliente_dueno: ClienteHttp,
    token_csrf: str,
    cliente_dispositivo: ClienteHttp,
    tipo: str,
    codigo: str,
    uid: str,
    request_id: str = "0001",
):
    inicio = crear_captura(cliente_dueno, token_csrf, tipo, codigo)
    exigir(inicio.estado == 201, f"iniciar captura {tipo}")
    captura_id = inicio.json()["capturaId"]
    exigir(len(captura_id) == 32, "capturaId compatible con protocolo serial")

    activa = cliente_dispositivo.solicitar(
        "GET", "/api/v1/dispositivos/rfid-1/capturas/activa"
    )
    exigir(activa.estado == 200 and activa.json().get("capturaId") == captura_id,
           "bridge consulta la captura autoritativa")
    estado = cliente_dispositivo.solicitar(
        "POST",
        f"/api/v1/dispositivos/rfid-1/capturas/{captura_id}/estado",
        {"estado": "ESCANEANDO"},
    )
    exigir(estado.estado == 204, "bridge informa ESCANEANDO")
    lectura = leer_tarjeta(cliente_dispositivo, captura_id, request_id, uid)
    return captura_id, lectura


def main() -> None:
    base_url = os.environ["RFID1_STAGE2_API_URL"].rstrip("/")
    token_dispositivo = os.environ["SMARTPARKING_RFID1_TOKEN"]
    SECRETOS_SINTETICOS.append(token_dispositivo)
    sufijo = uuid.uuid4().hex[:10]

    anonimo = ClienteHttp(base_url)
    respuesta = anonimo.solicitar("GET", "/api/v1/rfid-1/capturas/activa")
    exigir(respuesta.estado == 401, "rutas de propietario exigen sesión DUENO")

    dispositivo_anonimo = ClienteHttp(base_url)
    respuesta = dispositivo_anonimo.solicitar("GET", "/api/v1/dispositivos/rfid-1/capturas/activa")
    exigir(respuesta.estado == 401, "rutas de dispositivo rechazan token ausente")

    dueno, token_csrf = crear_propietario(base_url, sufijo)
    respuesta = dueno.solicitar("GET", "/api/v1/dispositivos/rfid-1/capturas/activa")
    exigir(respuesta.estado == 401, "cookie DUENO no autentica rutas del dispositivo")
    dispositivo = ClienteHttp(base_url, bearer=token_dispositivo)
    respuesta = dispositivo.solicitar(
        "GET", "/api/v1/rfid-1/capturas/activa"
    )
    exigir(respuesta.estado == 401, "Bearer del dispositivo no autentica rutas DUENO")
    respuesta = dueno.solicitar("POST", "/api/v1/rfid-1/capturas", {"tipoEntidad": "CLIENTE"})
    exigir(respuesta.estado == 403, "CSRF requerido en captura DUENO")

    empleado = crear_empleado(dueno, token_csrf, sufijo)
    cliente_codigo = crear_cliente(dueno, token_csrf, base_url, sufijo)

    from aceptacion_serie import probar_cancelacion_serial, probar_reinicio_serial, probar_serial

    empleado_serial = crear_empleado(dueno, token_csrf, sufijo + "s")
    uids_bridge, salida_bridge = probar_serial(
        base_url,
        token_dispositivo,
        dueno,
        token_csrf,
        empleado_serial["codigo"],
        crear_captura,
        exigir,
    )
    UID_SINTETICOS.extend(uids_bridge)
    empleado_reinicio = crear_empleado(dueno, token_csrf, sufijo + "r")
    uids_reinicio, salida_reinicio = probar_reinicio_serial(
        base_url,
        token_dispositivo,
        dueno,
        token_csrf,
        empleado_reinicio["codigo"],
        crear_captura,
        exigir,
    )
    UID_SINTETICOS.extend(uids_reinicio)
    salida_bridge += salida_reinicio
    empleado_cancelacion = crear_empleado(dueno, token_csrf, sufijo + "c")
    salida_bridge += probar_cancelacion_serial(
        base_url,
        token_dispositivo,
        dueno,
        token_csrf,
        empleado_cancelacion["codigo"],
        crear_captura,
        exigir,
    )
    uid_cliente = nuevo_uid()
    tipo_invalido = crear_captura(dueno, token_csrf, "VISITANTE", cliente_codigo)
    exigir(tipo_invalido.estado == 400, "tipo de entidad fuera de CLIENTE/EMPLEADO se rechaza")

    clave_inicio = clave_idempotencia()
    inicio = crear_captura(dueno, token_csrf, "CLIENTE", cliente_codigo, clave_inicio)
    exigir(inicio.estado == 201, "DUENO inicia captura para CLIENTE")
    captura_id = inicio.json()["capturaId"]
    repetida = crear_captura(dueno, token_csrf, "CLIENTE", cliente_codigo, clave_inicio)
    exigir(repetida.estado == 201 and repetida.json().get("capturaId") == captura_id,
           "replay de inicio devuelve la misma captura")
    conflicto_clave = crear_captura(
        dueno, token_csrf, "EMPLEADO", empleado["codigo"], clave_inicio
    )
    exigir(conflicto_clave.estado == 409, "clave de inicio con otro destino entra en conflicto")
    ocupada = crear_captura(dueno, token_csrf, "EMPLEADO", empleado["codigo"])
    exigir(ocupada.estado == 409, "solo existe una captura activa")

    activa = dispositivo.solicitar(
        "GET",
        "/api/v1/dispositivos/rfid-1/capturas/activa",
        encabezados={"Authorization": f"Bearer {token_dispositivo}"},
    )
    exigir(activa.estado == 200 and activa.json().get("capturaId") == captura_id,
           "Bearer autorizado recupera captura activa")
    estado = dispositivo.solicitar(
        "POST",
        f"/api/v1/dispositivos/rfid-1/capturas/{captura_id}/estado",
        {"estado": "ESCANEANDO"},
        {"Authorization": f"Bearer {token_dispositivo}"},
    )
    exigir(estado.estado == 204, "transición PENDIENTE a ESCANEANDO")

    request_id = "0001"
    clave_incorrecta = clave_lectura(captura_id, "0002")
    incorrecta = dispositivo.solicitar(
        "POST",
        "/api/v1/dispositivos/rfid-1/lecturas",
        {"capturaId": captura_id, "requestId": request_id, "uid": uid_cliente},
        {"Authorization": f"Bearer {token_dispositivo}", "Idempotency-Key": clave_incorrecta},
    )
    exigir(incorrecta.estado in (400, 409), "requestId debe corresponder con Idempotency-Key")

    lectura = leer_tarjeta(dispositivo, captura_id, request_id, uid_cliente)
    exigir(lectura.estado == 200 and lectura.json().get("resultado") == "ASOCIADA",
           "ENROLL_READ asocia CLIENTE")
    cuerpo_lectura = json.dumps(lectura.json(), ensure_ascii=True)
    exigir(uid_cliente not in cuerpo_lectura, "respuesta de asociación no revela UID")
    repetida = leer_tarjeta(dispositivo, captura_id, request_id, uid_cliente)
    exigir(repetida.estado == 200 and repetida.json().get("resultado") == "ASOCIADA",
           "replay de lectura devuelve el resultado confirmado")
    captura_ajena = "0" * 32 if captura_id != "0" * 32 else "1" * 32
    lectura_ajena = leer_tarjeta(dispositivo, captura_ajena, "0001", nuevo_uid())
    exigir(lectura_ajena.estado == 409, "ENROLL_READ con captura ajena se rechaza")

    estado_final = dueno.solicitar("GET", f"/api/v1/rfid-1/capturas/{captura_id}")
    exigir(estado_final.estado == 200 and estado_final.json().get("estado") == "COMPLETADA",
           "captura termina COMPLETADA")
    respuesta = crear_captura(dueno, token_csrf, "CLIENTE", cliente_codigo)
    exigir(respuesta.estado == 409, "persona asociada no puede recibir otra tarjeta")

    uid_empleado = nuevo_uid()
    captura_empleado, lectura_empleado = iniciar_y_leer(
        dueno, token_csrf, dispositivo, "EMPLEADO", empleado["codigo"], uid_empleado
    )
    exigir(lectura_empleado.estado == 200 and lectura_empleado.json().get("resultado") == "ASOCIADA",
           "ENROLL_READ asocia EMPLEADO")

    inicio_empleado2 = crear_empleado(dueno, token_csrf, sufijo + "i")
    UID_SINTETICOS.append(uid_cliente.lower())
    captura_dup, lectura_dup = iniciar_y_leer(
        dueno, token_csrf, dispositivo, "EMPLEADO", inicio_empleado2["codigo"], uid_cliente.lower(), "0002"
    )
    exigir(lectura_dup.estado == 409, "UID global duplicado se rechaza")
    estado_dup = dueno.solicitar("GET", f"/api/v1/rfid-1/capturas/{captura_dup}")
    exigir(estado_dup.estado == 200 and estado_dup.json().get("estado") == "RECHAZADA",
           "conflicto de UID termina como RECHAZADA")

    uid_ordinario = nuevo_uid()
    ordinaria = dispositivo.solicitar(
        "POST",
        "/api/v1/dispositivos/rfid-1/lecturas",
        {"secuencia": 42, "uid": uid_ordinario},
        {"Authorization": f"Bearer {token_dispositivo}", "Idempotency-Key": clave_idempotencia()},
    )
    exigir(ordinaria.estado == 202 and ordinaria.json() == {"estado": "RECIBIDA", "accion": "NINGUNA"},
           "lectura RFID ordinaria conserva comportamiento Stage 1")

    captura_ordinaria, lectura_ordinaria = iniciar_y_leer(
        dueno, token_csrf, dispositivo, "EMPLEADO", inicio_empleado2["codigo"], uid_ordinario, "0003"
    )
    exigir(lectura_ordinaria.estado == 200 and lectura_ordinaria.json().get("resultado") == "ASOCIADA",
           "lectura Stage 1 no crea asociación de negocio")

    empleado_inactivo = crear_empleado(dueno, token_csrf, sufijo + "x")
    inactivar_empleado(dueno, token_csrf, empleado_inactivo)
    captura_inactiva, lectura_inactiva = iniciar_y_leer(
        dueno, token_csrf, dispositivo, "EMPLEADO", empleado_inactivo["codigo"],
        nuevo_uid(), "0004"
    )
    exigir(lectura_inactiva.estado == 200 and lectura_inactiva.json().get("resultado") == "ASOCIADA",
           "asociar persona INACTIVA no la activa ni concede permiso")

    cliente_cancelable = crear_cliente(dueno, token_csrf, base_url, sufijo + "c")
    cancelable = crear_captura(dueno, token_csrf, "CLIENTE", cliente_cancelable)
    exigir(cancelable.estado == 201, "captura rechazada libera lector")
    cancelacion = dueno.solicitar(
        "DELETE",
        f"/api/v1/rfid-1/capturas/{cancelable.json()['capturaId']}",
        encabezados={"X-CSRF-TOKEN": token_csrf},
    )
    exigir(cancelacion.estado == 204, "DUENO cancela captura pendiente")
    repetida_cancelacion = dueno.solicitar(
        "DELETE",
        f"/api/v1/rfid-1/capturas/{cancelable.json()['capturaId']}",
        encabezados={"X-CSRF-TOKEN": token_csrf},
    )
    exigir(repetida_cancelacion.estado == 204, "cancelación es idempotente")

    no_encontrada = crear_captura(dueno, token_csrf, "CLIENTE", "CLI-999999999")
    exigir(no_encontrada.estado == 404, "destino inexistente se rechaza")

    sin_captura = dispositivo.solicitar(
        "GET",
        "/api/v1/dispositivos/rfid-1/capturas/activa",
        encabezados={"Authorization": f"Bearer {token_dispositivo}"},
    )
    exigir(sin_captura.estado == 204, "dispositivo recibe 204 sin captura activa")

    logs = subprocess.run(
        ["podman", "logs", os.environ["RFID1_STAGE2_API_CONTAINER"]],
        capture_output=True,
        text=True,
        check=True,
    )
    texto_logs = logs.stdout + logs.stderr
    exigir(
        all(secreto not in texto_logs and secreto not in salida_bridge for secreto in SECRETOS_SINTETICOS)
        and all(uid not in texto_logs and uid not in salida_bridge for uid in UID_SINTETICOS),
        "logs API y bridge omiten UID, Bearer y contraseñas sintéticas",
    )


if __name__ == "__main__":
    main()
