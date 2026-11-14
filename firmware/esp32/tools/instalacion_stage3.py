"""Instala los archivos de RFID3 mediante una conexión preparada para mantenimiento."""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath


ARCHIVOS = (
    "config.py", "aplicacion.py", "buzzer.py", "entrada_rfid2.py",
    "comunicacion/serial.py", "comunicacion/protocolo.py", "salida_rfid3.py",
)
NUEVO = "salida_rfid3.py"
MAXIMO_INTENTOS_RECUPERACION = 2


class ErrorInstalacion(RuntimeError):
    """Indica dónde se detuvo la instalación sin mostrar los mensajes de la placa."""

    def __init__(self, etapa, recuperado, sesion):
        self.etapa = etapa
        self.recuperado = recuperado
        self.sesion = sesion
        estado = ("sin cambios remotos" if recuperado is None else
                  "recuperación verificada" if recuperado else "recuperación incompleta")
        super().__init__("Instalación detenida en {}: {}.".format(etapa, estado))


def _nombre(nombre):
    if (not isinstance(nombre, str) or not nombre or not nombre.isascii()
            or nombre.startswith("/") or "\\" in nombre or "\x00" in nombre):
        raise ValueError("Ruta local inválida.")
    ruta = PurePosixPath(nombre)
    if any(parte in (".", "..") for parte in ruta.parts) or str(ruta) != nombre:
        raise ValueError("Ruta local inválida.")
    return nombre


def _archivo(base, nombre):
    ruta = Path(base)
    if ruta.is_symlink():
        raise ValueError("El directorio no puede ser un enlace.")
    for parte in _nombre(nombre).split("/"):
        ruta = ruta / parte
        if ruta.is_symlink():
            raise ValueError("El archivo no puede ser un enlace.")
    return ruta


def _huella(datos):
    return hashlib.sha256(datos).hexdigest()


def _huella_valida(valor):
    return isinstance(valor, str) and re.fullmatch(r"[0-9a-f]{64}", valor) is not None


def _validar_arbol(ruta, archivos_esperados):
    """Comprueba que la carpeta tenga exactamente los archivos previstos y ningún enlace."""
    ruta = Path(ruta)
    if ruta.is_symlink() or not ruta.is_dir():
        raise ValueError("Directorio local inesperado.")
    observados = set()
    for entrada in ruta.rglob("*"):
        if entrada.is_symlink():
            raise ValueError("El árbol local no puede contener enlaces.")
        if entrada.is_file():
            observados.add(entrada.relative_to(ruta).as_posix())
        elif not entrada.is_dir():
            raise ValueError("El árbol local contiene una entrada no regular.")
    if observados != set(archivos_esperados):
        raise ValueError("El inventario local no coincide con su manifiesto.")


def _validar_local(candidato, respaldo, archivos=ARCHIVOS, nuevo=NUEVO):
    """Revisa que los archivos nuevos y sus respaldos coincidan con sus registros."""
    archivos = tuple(archivos)
    if not archivos or len(set(archivos)) != len(archivos):
        raise ValueError("Lista de archivos inválida.")
    for nombre in archivos:
        _nombre(nombre)
    if nuevo is not None and nuevo not in archivos:
        raise ValueError("Archivo nuevo fuera de la lista aprobada.")
    candidato, respaldo = Path(candidato), Path(respaldo)
    if candidato.is_symlink() or respaldo.is_symlink():
        raise ValueError("El directorio no puede ser un enlace.")
    manifiesto_candidato = json.loads(_archivo(candidato, "sha256.json").read_text())
    if not isinstance(manifiesto_candidato, dict) or set(manifiesto_candidato) != set(archivos):
        raise ValueError("Manifiesto de candidato inesperado.")
    _validar_arbol(candidato, set(archivos) | {"sha256.json"})
    tamanos_candidato = {}
    for nombre, esperado in manifiesto_candidato.items():
        datos = _archivo(candidato, nombre).read_bytes()
        if not _huella_valida(esperado) or _huella(datos) != esperado:
            raise ValueError("Candidato alterado.")
        tamanos_candidato[nombre] = len(datos)

    registros = json.loads(_archivo(respaldo, "manifiesto.json").read_text())
    if not isinstance(registros, list) or not registros:
        raise ValueError("Manifiesto de respaldo inesperado.")
    originales = {}
    for registro in registros:
        nombre = _nombre(registro["ruta"])
        tamano, esperado = registro["bytes"], registro["sha256"]
        if (nombre in originales or nombre == "maintenance.flag" or not _huella_valida(esperado)
                or not isinstance(tamano, int) or isinstance(tamano, bool) or not 0 <= tamano <= 100000):
            raise ValueError("Entrada de respaldo inválida.")
        datos = _archivo(respaldo, nombre).read_bytes()
        if len(datos) != tamano or _huella(datos) != esperado:
            raise ValueError("Respaldo alterado.")
        originales[nombre] = (tamano, esperado)
    _validar_arbol(respaldo, set(originales) | {"manifiesto.json"})
    archivos_originales = set(archivos) - ({nuevo} if nuevo is not None else set())
    if (nuevo is not None and nuevo in originales) or not archivos_originales.issubset(originales):
        raise ValueError("El respaldo no corresponde a los originales esperados.")
    cambios = {
        nombre: (originales[nombre][1] if nombre in originales else None,
                 manifiesto_candidato[nombre])
        for nombre in archivos
    }
    if any(antes is not None and antes == despues for antes, despues in cambios.values()):
        raise ValueError("El candidato contiene un archivo sin cambios.")
    return originales, cambios, tamanos_candidato


def _bandera(repl):
    if not repl.existe("/maintenance.flag"):
        raise RuntimeError("Falta la bandera de mantenimiento propia.")
    valor = repl.consultar_linea(
        "FLAG:", "f=open('/maintenance.flag','rb'); b=f.read(); f.close(); "
        "print('FLAG:'+ubinascii.hexlify(b).decode())",
    )
    if valor != "310a":
        raise RuntimeError("Bandera de mantenimiento inesperada.")


class _Remoto:
    """Permite consultar, mover y borrar archivos de la placa durante el mantenimiento."""

    def __init__(self, repl):
        self.repl = repl

    @staticmethod
    def _ruta(nombre):
        return nombre if nombre.startswith("/") else "/" + nombre

    def existe(self, nombre):
        return self.repl.existe(self._ruta(nombre))

    def sha256_remoto(self, nombre):
        return self.repl.sha256_remoto(self._ruta(nombre))

    def renombrar(self, origen, destino):
        self.repl.comando("os.rename({!r},{!r})".format(
            self._ruta(origen), self._ruta(destino),
        ))

    def eliminar(self, nombre):
        self.repl.comando("os.remove({!r})".format(self._ruta(nombre)))


def _verificar_estado(
        repl, inventariar, originales, cambios, tamanos, temporal, instalado,
        archivos=ARCHIVOS, nuevo=NUEVO):
    """Comprueba que los archivos de la placa coincidan con los esperados."""
    observados = inventariar(repl)
    if not isinstance(observados, dict) or observados.get("maintenance.flag") != 2:
        raise RuntimeError("Inventario remoto inesperado.")
    excluido = temporal.lstrip("/") + "/"
    observados = {nombre: tamano for nombre, tamano in observados.items()
                  if nombre != "maintenance.flag" and not nombre.startswith(excluido)}
    esperados = {nombre: dato[0] for nombre, dato in originales.items()}
    if instalado:
        esperados.update(tamanos)
    if observados != esperados:
        raise RuntimeError("Inventario remoto diferente del esperado.")
    remoto = _Remoto(repl)
    for nombre, (_, huella_original) in originales.items():
        esperado = cambios[nombre][1] if instalado and nombre in cambios else huella_original
        if remoto.sha256_remoto(nombre) != esperado:
            raise RuntimeError("Un archivo remoto no coincide.")
    if not instalado and nuevo is not None and remoto.existe(nuevo):
        raise RuntimeError("Permanece un archivo nuevo inesperado.")


def _resincronizar(sesion, callback):
    """Recupera el acceso a la placa y comprueba que siga en mantenimiento."""
    reemplazo = callback(sesion[0])
    if reemplazo is not None:
        sesion[0] = reemplazo
    repl = sesion[0]
    repl.preparar_escritura()
    _bandera(repl)
    return repl


def _verificar_prueba(resultado):
    """Revisa el informe de arranque recibido.

    Debe indicar que se cargaron los archivos necesarios, los tres lectores están listos y hubo
    al menos tres respuestas, sin lecturas ni reinicios inesperados.
    """
    lectores = {nombre: "READY" for nombre in ("RFID1", "RFID2", "RFID3")}
    if (not isinstance(resultado, dict) or resultado.get("imports") is not True
            or resultado.get("lectores") != lectores or type(resultado.get("pongs")) is not int
            or resultado["pongs"] < 3 or type(resultado.get("reinicios_inesperados")) is not int
            or resultado["reinicios_inesperados"] != 0 or type(resultado.get("lecturas")) is not int
            or resultado["lecturas"] != 0):
        raise RuntimeError("La prueba de inicialización no está completa.")


def _verificar_copias(repl, temporal, originales, carpetas, archivos=ARCHIVOS, nuevo=NUEVO):
    for nombre in archivos:
        if nombre == nuevo or nombre not in originales:
            continue
        for carpeta in carpetas:
            if repl.sha256_remoto(temporal + "/" + carpeta + "/" + nombre) != originales[nombre][1]:
                raise RuntimeError("La copia remota de recuperación difiere.")


def instalar_archivos(*, repl, candidato, respaldo, temporal, promocion,
                      inventariar, resincronizar, verificar_arranque,
                      archivos, nuevo=None):
    """Instala los archivos o recupera los anteriores mientras la placa está en mantenimiento.

    Las funciones recibidas comprueban el arranque sin usar tarjetas y recuperan
    el acceso a la placa. Si cambian la conexión, deben cerrar la anterior.
    Los archivos de recuperación y la señal de mantenimiento se conservan.
    """
    try:
        originales, cambios, tamanos = _validar_local(
            candidato, respaldo, archivos=archivos, nuevo=nuevo,
        )
        if not isinstance(temporal, str) or not re.fullmatch(r"/sp_[A-Za-z0-9_]{3,56}", temporal):
            raise ValueError("Directorio temporal inválido.")
    except Exception:
        raise ErrorInstalacion("preparación local", None, repl) from None

    etapa = "preflight remoto"
    promocion_iniciada = False
    sesion = [repl]
    try:
        repl.preparar_escritura()
        _bandera(repl)
        _verificar_estado(
            repl, inventariar, originales, cambios, tamanos, temporal, False,
            archivos=archivos, nuevo=nuevo,
        )
        archivos_originales = [nombre for nombre in archivos if nombre in originales]
        espacio_necesario = sum(tamanos.values()) + sum(
            originales[nombre][0] for nombre in archivos_originales
        )
        if repl.existe(temporal) or repl.espacio_disponible() < max(131072, espacio_necesario + 65536):
            raise RuntimeError("No hay espacio o el destino temporal existe.")
        etapa = "preparación remota"
        sufijos = ["", "/nuevo", "/original", "/resguardo"]
        for nombre in archivos:
            padre = PurePosixPath(nombre).parent
            if str(padre) != ".":
                partes = []
                for parte in padre.parts:
                    partes.append(parte)
                    sufijo = "/" + "/".join(partes)
                    for base in ("nuevo", "original", "resguardo"):
                        ruta = "/" + base + sufijo
                        if ruta not in sufijos:
                            sufijos.append(ruta)
        for sufijo in sufijos:
            repl.crear_directorio(temporal + sufijo)
        for nombre in archivos_originales:
            destino = temporal + "/resguardo/" + nombre
            repl.transferir(_archivo(respaldo, nombre), destino)
            if repl.sha256_remoto(destino) != originales[nombre][1]:
                raise RuntimeError("La copia remota de recuperación difiere.")
        for nombre in archivos:
            destino = temporal + "/nuevo/" + nombre
            repl.transferir(_archivo(candidato, nombre), destino)
            if repl.sha256_remoto(destino) != cambios[nombre][1]:
                raise RuntimeError("El candidato remoto difiere.")
            codigo = "compile(open({!r}).read(), {!r}, 'exec'); print('COMPILA:OK')".format(destino, destino)
            if repl.consultar_linea("COMPILA:", codigo) != "OK":
                raise RuntimeError("El candidato no compiló en la placa.")
        etapa = "promoción"
        promocion_iniciada = True
        promocion.promover(_Remoto(repl), cambios, temporal + "/nuevo", temporal + "/original")
        _verificar_estado(
            repl, inventariar, originales, cambios, tamanos, temporal, True,
            archivos=archivos, nuevo=nuevo,
        )
        etapa = "arranque"
        resultado = verificar_arranque(repl)
        _verificar_prueba(resultado)
        etapa = "verificación final"
        repl = _resincronizar(sesion, resincronizar)
        _verificar_estado(
            repl, inventariar, originales, cambios, tamanos, temporal, True,
            archivos=archivos, nuevo=nuevo,
        )
        _verificar_copias(
            repl, temporal, originales, ("resguardo", "original"),
            archivos=archivos, nuevo=nuevo,
        )
        return {"sesion": repl, "temporal": temporal, "prueba": resultado}
    except BaseException:
        for _ in range(MAXIMO_INTENTOS_RECUPERACION):
            try:
                repl = _resincronizar(sesion, resincronizar)
                if promocion_iniciada:
                    promocion.recuperar(_Remoto(repl), cambios, temporal + "/original")
                    _verificar_estado(
                        repl, inventariar, originales, cambios, tamanos, temporal, False,
                        archivos=archivos, nuevo=nuevo,
                    )
                if promocion_iniciada:
                    _verificar_copias(
                        repl, temporal, originales, ("resguardo",),
                        archivos=archivos, nuevo=nuevo,
                    )
            except BaseException:
                repl = sesion[0]
                continue
            raise ErrorInstalacion(etapa, True, repl) from None
        raise ErrorInstalacion(etapa, False, repl) from None


def instalar_stage3(*, repl, candidato, respaldo, temporal, promocion,
                    inventariar, resincronizar, verificar_arranque):
    """Inicia la instalación de RFID3 mediante la forma de uso anterior."""
    return instalar_archivos(
        repl=repl, candidato=candidato, respaldo=respaldo, temporal=temporal,
        promocion=promocion, inventariar=inventariar,
        resincronizar=resincronizar, verificar_arranque=verificar_arranque,
        archivos=ARCHIVOS, nuevo=NUEVO,
    )
