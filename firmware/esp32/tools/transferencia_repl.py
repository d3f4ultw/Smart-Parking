"""Copia archivos hacia la placa mediante una conexión de mantenimiento."""

import base64
import hashlib
import re
import time
from pathlib import Path

import serial


TAMANO_BLOQUE = 72
TIEMPO_ESPERA_PROMPT = 6.0
INTENTOS_BLOQUE = 2
PATRON_ACK = re.compile(rb"ACK:(\d+)")
PATRON_DATOS = re.compile(rb"(?m)^DATA:([A-Za-z0-9+/=]+)\s*$")


class ErrorTransferencia(RuntimeError):
    """Indica que no se pudo confirmar una operación sobre los archivos de la placa."""


class ReplFriendly:
    """Mantiene una conexión para enviar órdenes sin pedir el reinicio de la placa."""

    def __init__(self, puerto):
        self.serie = serial.Serial(
            port=None,
            baudrate=115200,
            timeout=0.1,
            write_timeout=2,
            rtscts=False,
            dsrdtr=False,
        )
        self.serie.dtr = False
        self.serie.rts = False
        self.serie.port = puerto
        self.serie.open()
        self._buffer = bytearray()

    def cerrar(self):
        """Cierra la conexión usada durante el mantenimiento."""
        self.serie.close()

    def entrar(self, permitir_stop=False):
        """Solicita acceso a la placa y solo envía la orden de detenerla si se permite."""
        time.sleep(0.3)
        self.serie.read(4096)
        self.serie.write(b"\x03")
        try:
            return self._leer_prompt(3.0)
        except TimeoutError:
            if not permitir_stop:
                raise ErrorTransferencia("No apareció el prompt REPL tras Ctrl-C.")
        self.serie.write(b"STOP\r\n")
        try:
            return self._leer_prompt(12.0)
        except TimeoutError as error:
            raise ErrorTransferencia("STOP no abrió un prompt REPL estable.") from error

    def comando(self, linea, timeout=TIEMPO_ESPERA_PROMPT):
        """Envía una orden a la placa y devuelve todo lo que respondió."""
        self.serie.write(linea.encode("ascii") + b"\r\n")
        salida = self._leer_prompt(timeout)
        if b"Traceback (most recent call last)" in salida:
            raise ErrorTransferencia(salida.decode("utf-8", "replace"))
        return salida

    def ejecutar(self, codigo, timeout=TIEMPO_ESPERA_PROMPT):
        """Envía varias líneas de instrucciones en una sola orden."""
        return self.comando("exec({!r})".format(codigo), timeout)

    def _leer_prompt(self, timeout):
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            posicion = self._buffer.find(b">>>")
            if posicion >= 0:
                fin = posicion + 3
                salida = bytes(self._buffer[:fin])
                del self._buffer[:fin]
                return salida
            parte = self.serie.read(1024)
            if parte:
                self._buffer.extend(parte)
        raise TimeoutError("Se agotó la espera del prompt REPL.")

    def consultar_linea(self, prefijo, comando):
        """Encuentra la última respuesta que empieza con el texto indicado."""
        salida = self.comando(comando).decode("utf-8", "replace")
        coincidencias = [
            linea.strip() for linea in salida.splitlines()
            if linea.strip().startswith(prefijo)
        ]
        if not coincidencias:
            raise ErrorTransferencia("La consulta remota no devolvió su marcador.")
        return coincidencias[-1][len(prefijo):]

    def preparar_escritura(self):
        """Prepara en la placa las herramientas necesarias para copiar archivos."""
        self.comando("import os,ubinascii,uhashlib")

    def existe(self, ruta):
        """Comprueba si ya existe un archivo o una carpeta con ese nombre."""
        padre, _, nombre = ruta.rpartition("/")
        padre = padre or "."
        resultado = self.consultar_linea(
            "EXISTS:",
            "print('EXISTS:'+str({!r} in __import__('os').listdir({!r})))".format(
                nombre, padre
            ),
        )
        return resultado == "True"

    def espacio_disponible(self):
        """Consulta cuánto espacio libre queda en la placa."""
        resultado = self.consultar_linea(
            "FREE:",
            "import os; s=os.statvfs('/'); print('FREE:'+str(s[0]*s[4]))",
        )
        return int(resultado)

    def sha256_remoto(self, ruta):
        """Obtiene una huella del archivo de la placa para comprobar su contenido."""
        codigo = (
            "f=open({!r},'rb'); d=f.read(); f.close(); "
            "print('SHA:'+ubinascii.hexlify(uhashlib.sha256(d).digest()).decode()); "
            "del d; del f"
        ).format(ruta)
        return self.consultar_linea("SHA:", codigo)

    def sondear_escritura(self):
        """Comprueba si la placa puede guardar, leer y borrar un archivo temporal."""
        ruta = ".sp-transfer-probe"
        if self.existe(ruta):
            raise ErrorTransferencia("Ya existe el archivo temporal de sondeo.")
        self.comando("f=open('.sp-transfer-probe','wb')")
        self.comando("f.write(b'SP-REPL-PROBE')")
        self.comando("f.close()")
        self.comando("f=open('.sp-transfer-probe','rb')")
        salida = self.comando("print('PROBE:'+str(f.read()))").decode("utf-8", "replace")
        self.comando("f.close()")
        self.comando("import os; os.remove('.sp-transfer-probe')")
        if "SP-REPL-PROBE" not in salida or self.existe(ruta):
            raise ErrorTransferencia("Falló el sondeo temporal del filesystem.")

    def crear_directorio(self, ruta):
        """Crea una carpeta necesaria en la placa y comprueba que puede consultarse."""
        self.comando("os.mkdir({!r})".format(ruta))
        self.comando("print('DIR_OK:'+str(type(os.listdir({!r})) is list))".format(ruta))

    def descargar(self, ruta, tamano, tamano_bloque=TAMANO_BLOQUE):
        """Lee el archivo de la placa por partes y reúne su contenido en el equipo."""
        resultado = bytearray()
        for offset in range(0, tamano, tamano_bloque):
            cantidad = min(tamano_bloque, tamano - offset)
            comando = (
                "f=open({!r},'rb'); f.seek({}); d=f.read({}); f.close(); "
                "print('DATA:'+ubinascii.b2a_base64(d).decode())"
            ).format(ruta, offset, cantidad)
            salida = self.comando(comando)
            coincidencias = PATRON_DATOS.findall(salida)
            if not coincidencias:
                raise ErrorTransferencia("Faltó un bloque de lectura remota.")
            bloque = base64.b64decode(coincidencias[-1])
            if len(bloque) != cantidad:
                raise ErrorTransferencia("El bloque leído tiene tamaño inesperado.")
            resultado.extend(bloque)
        return bytes(resultado)

    def transferir(self, origen, destino):
        """Copia un archivo, comprueba su contenido y le asigna el nombre definitivo."""
        contenido = Path(origen).read_bytes()
        temporal = destino + ".part"
        if self.existe(temporal):
            raise ErrorTransferencia("Ya existe un temporal remoto: " + temporal)
        self.ejecutar("open({!r},'wb').close(); print('FILE_READY')".format(temporal))
        for offset in range(0, len(contenido), TAMANO_BLOQUE):
            bloque = contenido[offset:offset + TAMANO_BLOQUE]
            codificado = base64.b64encode(bloque).decode("ascii")
            confirmado = False
            for intento in range(INTENTOS_BLOQUE):
                linea = (
                    "f=open({!r},'ab'); f.write(ubinascii.a2b_base64('{}')); "
                    "f.close(); print('ACK:'+str(os.stat({!r})[6]))"
                ).format(temporal, codificado, temporal)
                try:
                    salida = self.comando(linea).decode("utf-8", "replace")
                except TimeoutError:
                    if intento + 1 == INTENTOS_BLOQUE:
                        raise ErrorTransferencia(
                            "El REPL no respondió para el bloque {}.".format(offset)
                        )
                    # Se recupera el acceso antes de revisar qué parte llegó a la placa.
                    try:
                        self._leer_prompt(2.0)
                    except TimeoutError as error:
                        raise ErrorTransferencia(
                            "No se recuperó el prompt después del bloque {}.".format(offset)
                        ) from error
                    salida = ""
                marcas = PATRON_ACK.findall(salida.encode("utf-8"))
                if marcas and int(marcas[-1]) == offset + len(bloque):
                    confirmado = True
                    break
                # Si falta la confirmación, comprueba lo guardado antes de repetir el envío.
                tamano_remoto = int(self.consultar_linea(
                    "SIZE:", "print('SIZE:'+str(os.stat({!r})[6]))".format(temporal)
                ))
                if tamano_remoto == offset + len(bloque):
                    codigo_lectura = (
                        "f=open({!r},'rb'); f.seek({}); d=f.read({}); f.close(); "
                        "print('DATA:'+ubinascii.b2a_base64(d).decode())"
                    ).format(temporal, offset, len(bloque))
                    coincidencias = PATRON_DATOS.findall(self.comando(codigo_lectura))
                    if coincidencias and base64.b64decode(coincidencias[-1]) == bloque:
                        confirmado = True
                        break
                    raise ErrorTransferencia("El bloque previo en el offset no coincide.")
                if tamano_remoto != offset:
                    raise ErrorTransferencia(
                        "Offset remoto inesperado: {}.".format(tamano_remoto)
                    )
                if intento + 1 < INTENTOS_BLOQUE:
                    # No llegó esta parte; el siguiente intento empieza en el mismo lugar.
                    continue
            if not confirmado:
                raise ErrorTransferencia(
                    "No se confirmó el bloque en offset {}.".format(offset)
                )
        remoto = self.descargar(temporal, len(contenido))
        esperado = hashlib.sha256(contenido).hexdigest()
        observado = hashlib.sha256(remoto).hexdigest()
        if remoto != contenido or observado != esperado:
            raise ErrorTransferencia("El checksum remoto difiere para " + destino)
        if self.existe(destino):
            raise ErrorTransferencia("No se reemplazará el destino existente: " + destino)
        self.ejecutar(
            "import os; os.rename({!r},{!r}); print('PROMOTED')".format(
                temporal, destino
            )
        )
        return len(contenido), esperado
