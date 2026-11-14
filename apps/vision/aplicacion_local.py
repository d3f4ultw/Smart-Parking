"""Permite dibujar y revisar las zonas sobre una imagen fija de la cámara."""

from __future__ import annotations

import copy
import json
import tempfile
import time
from pathlib import Path
from uuid import UUID

import cv2

from calibracion_automatica import ErrorCalibracionAutomatica, generar_candidato_automatico
from calibracion_zonas import cargar_calibracion, guardar_calibracion
from calibrar_zonas import (
    ALTO_CABECERA, COLOR_AVISO, COLOR_FONDO, COLOR_PRINCIPAL, COLOR_SECUNDARIO,
    COLOR_SEPARADOR, ControlRaton, RADIO_VERTICE_PX,
    _misma_geometria_e_identidades, _restaurar_par_calibracion, dibujar_superposicion,
)
from configuracion_local import (
    _comprobar_guardado_propio, _sidecar_compatible, finalizar_guardado_pendiente,
    guardar_vinculo, identidad_fuente, preparar_guardado_calibracion, ruta_vinculo,
    verificar_sin_guardado_pendiente, verificar_vinculo,
)
from temporal_validation import FrameQualityGuard, ParkingZone


def validar_ruta_local(directorio: Path | None, ruta_zonas: Path) -> None:
    """Comprueba que las zonas locales se guarden aparte de los archivos habituales."""
    if directorio is None or not directorio.is_dir():
        raise ValueError("LOCAL requiere un directorio de calibracion existente y exclusivo.")
    carpeta = directorio.resolve()
    if carpeta == Path("/data/config").resolve():
        raise ValueError("LOCAL requiere una copia separada de /data/config.")
    if (ruta_zonas.parent.resolve() != carpeta or ruta_zonas.is_symlink()
            or ruta_vinculo(ruta_zonas).is_symlink()):
        raise ValueError("La calibracion LOCAL debe estar en el directorio indicado, sin enlaces.")
    if not ruta_zonas.is_file():
        raise ValueError("La copia LOCAL de zones.json no existe.")


def _identidades_y_atributos(datos: dict, calibracion) -> dict[str, dict]:
    registros = datos.get("zones")
    if not isinstance(registros, list) or len(registros) != len(calibracion.zonas):
        raise ValueError("La lista de zonas no coincide con la calibracion cargada.")
    atributos = {}
    identidades = set()
    for registro in registros:
        if not isinstance(registro, dict):
            raise ValueError("La zona no tiene una identidad valida.")
        etiqueta = registro.get("id")
        try:
            identidad = UUID(registro["vision_zone_id"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError("Cada zona requiere su vision_zone_id original.") from error
        if (etiqueta in atributos or identidad in identidades
                or calibracion.vision_zone_ids.get(etiqueta) != identidad):
            raise ValueError("Las etiquetas e identidades de zona deben ser unicas.")
        identidades.add(identidad)
        atributos[etiqueta] = {
            clave: valor for clave, valor in registro.items()
            if clave not in {"id", "vision_zone_id", "polygon"}
        }
    if set(atributos) != set(calibracion.zonas):
        raise ValueError("Los atributos no corresponden con las zonas activas.")
    return atributos


def validar_archivo_local(ruta: Path, tipo: str, fuente: str, dimensiones=None, *, recuperar=True):
    """Comprueba que las zonas guardadas correspondan al origen y tamaño de la imagen.

    Después carga las zonas y los datos asociados, o informa que el archivo no coincide.
    """
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    metadata = datos.get("metadata") if isinstance(datos, dict) else None
    if not isinstance(metadata, dict):
        raise ValueError("La calibracion LOCAL requiere metadatos canonicos.")
    ancho, alto = metadata.get("source_width"), metadata.get("source_height")
    if (not isinstance(ancho, int) or isinstance(ancho, bool) or ancho < 2
            or not isinstance(alto, int) or isinstance(alto, bool) or alto < 2
            or (dimensiones is not None and (alto, ancho) != dimensiones)):
        raise ValueError("Las dimensiones de la fuente no coinciden con la calibracion LOCAL.")
    if recuperar:
        verificar_vinculo(ruta, tipo, fuente, ancho, alto)
    else:
        try:
            vinculo = json.loads(ruta_vinculo(ruta).read_text(encoding="utf-8"))
            compatible = _sidecar_compatible(ruta, vinculo, tipo, fuente, ancho, alto)
        except (OSError, ValueError, TypeError, KeyError):
            compatible = False
        if not compatible:
            raise ValueError("El par de calibracion no coincide; no se modifico.")
    calibracion = cargar_calibracion(ruta, ancho, alto)
    atributos = _identidades_y_atributos(datos, calibracion)
    if (metadata.get("source_type") != tipo
            or metadata.get("fuente_sha256") != identidad_fuente(tipo, fuente)):
        raise ValueError("La calibracion no coincide con la fuente activa.")
    return calibracion, atributos


def _restaurar_json(ruta: Path, respaldo: Path) -> None:
    """Recupera ambos archivos del par desde una copia anterior."""
    _restaurar_par_calibracion(ruta, respaldo)


def _cargar_copia_guardado(ruta: Path, contenido: bytes, ancho: int, alto: int):
    """Valida una copia privada mientras el par original sigue bloqueado."""
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=ruta.parent,
                                         prefix=f".{ruta.name}.validar-", delete=False) as salida:
            temporal = Path(salida.name)
            salida.write(contenido)
        return cargar_calibracion(temporal, ancho, alto)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


class _ErrorGuardadoRecuperado(ValueError):
    """El guardado falló, pero se recuperó la copia anterior."""


class EditorLocal:
    """Permite dibujar y revisar cambios en las zonas sobre una imagen fija antes de guardarlos."""

    def __init__(self, ruta: Path, tipo: str, fuente: str, muestra, *, recuperar=True) -> None:
        self.ruta = ruta
        self.tipo = tipo
        self.fuente = fuente
        self.imagen = muestra.cuadro.copy()
        self.generacion = muestra.generacion
        self.alto, self.ancho = self.imagen.shape[:2]
        self.original, self.atributos = validar_archivo_local(
            ruta, tipo, fuente, (self.alto, self.ancho), recuperar=recuperar)
        self.borrador = copy.deepcopy(self.original)
        self.control = ControlRaton(self.borrador)
        self.control.mensaje = "Selecciona una zona y arrastra sus vertices."
        self.historial = []
        self.antes_arrastre = None
        self.propuesta = None
        self.creando_poligono = False
        self.fuente_cambiada = False
        self.fuente_valida = True
        self.guardia_fuente = FrameQualityGuard()
        self.calidad_fuente = self.guardia_fuente.inspect(muestra.cuadro)[0]
        self.revision_fuente = muestra.revision
        self.bloqueado = False

    def actualizar_fuente(self, muestra, max_edad: float) -> None:
        """Comprueba que la cámara siga conectada y entregue una imagen reciente y válida.

        También exige que la conexión y el tamaño de la imagen no hayan cambiado.
        """
        if muestra.generacion != self.generacion:
            self.fuente_cambiada = True
        fresca = (muestra.estado == "conectada" and muestra.cuadro is not None
                  and muestra.momento is not None
                  and 0 <= time.monotonic() - muestra.momento <= max_edad)
        if fresca and muestra.revision != self.revision_fuente:
            self.calidad_fuente = self.guardia_fuente.inspect(muestra.cuadro)[0]
            self.revision_fuente = muestra.revision
        self.fuente_valida = bool(
            fresca and not self.fuente_cambiada
            and muestra.cuadro.shape[:2] == (self.alto, self.ancho)
            and self.calidad_fuente
        )

    def raton(self, evento, x, y, flags, datos) -> None:
        if self.propuesta is not None or self.bloqueado:
            return
        if self.creando_poligono:
            if evento == cv2.EVENT_LBUTTONDOWN:
                _, self.control.mensaje = self.borrador.agregar_punto(x, y)
            return
        if evento == cv2.EVENT_LBUTTONDOWN:
            seleccionado = self.borrador.id_seleccionado
            radio = min(RADIO_VERTICE_PX, max(5, round(min(self.ancho, self.alto) * 0.01)))
            vertice = (self.borrador.vertice_cercano(x, y, radio, identificador=seleccionado)
                       if seleccionado else None)
            if vertice is None and self.borrador.zona_en_punto(x, y) is None:
                self.control.mensaje = "Selecciona una zona o pulsa N para crearla."
                return
            self.antes_arrastre = copy.deepcopy(self.borrador)
        arrastraba = self.control.arrastre is not None
        self.control.procesar_evento(evento, x, y, flags, datos)
        if evento == cv2.EVENT_LBUTTONUP:
            if (arrastraba and self.antes_arrastre is not None
                    and not _misma_geometria_e_identidades(self.antes_arrastre, self.borrador)):
                self._recordar(self.antes_arrastre)
            self.antes_arrastre = None

    def _recordar(self, calibracion) -> None:
        self.historial.append(calibracion)
        if len(self.historial) > 50:
            self.historial.pop(0)

    def _usar_borrador(self, calibracion) -> None:
        self.borrador = calibracion
        self.control = ControlRaton(self.borrador)
        self.creando_poligono = bool(self.borrador.puntos_pendientes)

    def botones_calibracion(self):
        x, y = self.ancho, ALTO_CABECERA
        return (
            ("Nuevo", ord("n"), (x + 14, y + 124, 112, 32)),
            ("Eliminar", ord("d"), (x + 134, y + 124, 112, 32)),
            ("Deshacer", ord("z"), (x + 14, y + 164, 112, 32)),
            ("Propuesta", ord("a"), (x + 134, y + 164, 112, 32)),
            ("Aceptar", 13, (x + 14, y + 212, 112, 32)),
            ("Descartar", ord("r"), (x + 134, y + 212, 112, 32)),
            ("Sincronizar y guardar", ord("s"), (x + 14, y + 260, 232, 36)),
            ("Cancelar", 27, (x + 14, y + 304, 232, 32)),
        )

    def tecla_de_boton(self, x: int, y: int) -> int | None:
        for _, tecla, (izquierda, arriba, ancho, alto) in self.botones_calibracion():
            if izquierda <= x < izquierda + ancho and arriba <= y < arriba + alto:
                return tecla
        return None

    def _dibujar_botones(self, lienzo) -> None:
        # Los colores de fondo y borde distinguen las acciones de la ventana.
        estilos = {
            ord("n"): ((64, 48, 34), (98, 73, 48)),
            ord("d"): ((40, 38, 64), (60, 56, 96)),
            ord("a"): ((65, 43, 54), (98, 65, 82)),
            13: ((42, 64, 36), (63, 94, 54)),
            ord("s"): ((57, 115, 42), (78, 150, 64)),
        }
        for desplazamiento in (204, 252):
            y = ALTO_CABECERA + desplazamiento
            cv2.line(lienzo, (self.ancho + 14, y), (self.ancho + 245, y),
                     COLOR_SEPARADOR, 1)
        for etiqueta, tecla, (x, y, ancho, alto) in self.botones_calibracion():
            extremo = (x + ancho - 1, y + alto - 1)
            fondo, borde = estilos.get(tecla, ((44, 44, 44), COLOR_SEPARADOR))
            color = COLOR_PRINCIPAL
            if ((tecla == 13 and self.propuesta is None and not self.creando_poligono)
                    or (tecla == ord("r") and self.propuesta is None)):
                color = COLOR_SECUNDARIO
                fondo, borde = (35, 35, 35), (48, 48, 48)
            cv2.rectangle(lienzo, (x, y), extremo, fondo, cv2.FILLED)
            cv2.rectangle(lienzo, (x, y), extremo, borde, 1)
            escala = 0.54 if tecla == ord("s") else 0.5
            (ancho_texto, alto_texto), base = cv2.getTextSize(
                etiqueta, cv2.FONT_HERSHEY_SIMPLEX, escala, 1,
            )
            origen = (x + (ancho - ancho_texto) // 2,
                      y + (alto + alto_texto - base) // 2)
            cv2.putText(lienzo, etiqueta, origen, cv2.FONT_HERSHEY_SIMPLEX,
                        escala, color, 1, cv2.LINE_AA)

    def tecla(self, tecla: int) -> str | None:
        if self.bloqueado:
            return None
        if tecla == 27:
            return "cancelar"
        if self.propuesta is not None:
            if tecla in (10, 13):
                self._recordar(copy.deepcopy(self.borrador))
                self._usar_borrador(self.propuesta)
                self.propuesta = None
                self.control.mensaje = "Propuesta aceptada en el borrador; S guarda."
            elif tecla in (ord("r"), ord("R")):
                self.propuesta = None
                self.control.mensaje = "Propuesta descartada; se conserva el borrador."
            elif tecla in (ord("s"), ord("S")):
                self.control.mensaje = "Revise la propuesta y pulse Enter o R antes de guardar."
            return None
        if tecla in (10, 13) and self.creando_poligono:
            anterior = copy.deepcopy(self.borrador)
            aceptado, self.control.mensaje = self.borrador.confirmar_poligono()
            if aceptado:
                self._recordar(anterior)
                self.creando_poligono = False
            return None
        if tecla in (ord("n"), ord("N")):
            if self.creando_poligono:
                self.control.mensaje = "Termina el poligono actual antes de iniciar otro."
            else:
                iniciado, self.control.mensaje = self.borrador.iniciar_nueva_zona()
                self.creando_poligono = iniciado
            return None
        if tecla in (ord("d"), ord("D")):
            anterior = copy.deepcopy(self.borrador)
            identificador = self.borrador.id_seleccionado
            self.control.mensaje = self.borrador.eliminar_zona()
            if identificador in anterior.zonas and identificador not in self.borrador.zonas:
                self._recordar(anterior)
            return None
        if tecla in (ord("a"), ord("A")):
            if self.control.arrastre is not None or self.creando_poligono:
                self.control.mensaje = "Termina el poligono o el arrastre antes de proponer."
                return None
            try:
                propuesta = generar_candidato_automatico(self.imagen, self.borrador).calibracion
                self._validar_borrador(propuesta, self.borrador)
            except (ErrorCalibracionAutomatica, ValueError, cv2.error) as error:
                self.control.mensaje = f"No se genero propuesta: {error}"
            else:
                self.propuesta = propuesta
                self.control.mensaje = "Revise la propuesta: Enter acepta, R descarta."
        elif tecla in (ord("z"), ord("Z")):
            if self.control.arrastre is not None:
                self.control.mensaje = "Termine el arrastre antes de deshacer."
            elif self.creando_poligono and self.borrador.puntos_pendientes:
                _, self.control.mensaje = self.borrador.deshacer_punto()
            elif self.creando_poligono:
                self.control.mensaje = self.borrador.cancelar_poligono()
                self.creando_poligono = False
            elif self.historial:
                self._usar_borrador(self.historial.pop())
                self.control.mensaje = "Se deshizo el ultimo cambio."
            else:
                self.control.mensaje = "No hay cambios para deshacer."
        elif tecla in (ord("s"), ord("S")):
            return "guardar"
        return None

    def pantalla(self, *, modo_permanente: bool = False,
                 sincronizacion_pendiente: bool = False):
        cierre = "Q/X: cerrar ventana" if modo_permanente else "Q: cerrar ventana"
        if sincronizacion_pendiente:
            instrucciones = [f"S: completar sincronizacion | {cierre}"]
        elif self.propuesta is not None:
            instrucciones = [
                "VISTA PREVIA AUTOMATICA | Enter: aceptar | R: descartar",
                f"Esc: cancelar | {cierre}",
            ]
        elif self.creando_poligono:
            instrucciones = [
                "Click izquierdo: vertices | Enter: confirmar | Z: quitar ultimo vertice",
                f"Esc: cancelar | {cierre}",
            ]
        else:
            guardar = "S: sincronizar y guardar" if modo_permanente else "S: guardar local"
            instrucciones = [
                "Click: seleccionar | Arrastrar vertice: editar | N: nuevo | D: eliminar",
                f"Z: deshacer | A: propuesta | {guardar} | Esc: cancelar | {cierre}",
            ]
        if not modo_permanente:
            instrucciones.append("LOCAL: sin sincronizacion con Java")
        fuente = "Fuente camara: "
        if self.fuente_cambiada:
            fuente += "cambio durante la edicion"
            instrucciones.append("Fuente cambio: cancele y entre de nuevo antes de guardar.")
        elif not self.fuente_valida:
            fuente += "no verificable para guardar"
            instrucciones.append("Fuente no verificable: guardado suspendido.")
        else:
            fuente += "valida para guardar | imagen congelada"
        if sincronizacion_pendiente:
            instrucciones.append("Java acepto el mapa; pulse S para completar.")
        elif self.bloqueado:
            instrucciones.append("Edicion bloqueada; revise el mensaje.")
        lienzo = dibujar_superposicion(
            self.imagen, self.propuesta or self.borrador, self.control.mensaje,
            poligono_temporal=self.control.poligono_temporal,
            instrucciones=instrucciones,
            marco=True, fuente=fuente,
        )
        self._dibujar_botones(lienzo)
        return lienzo

    def _validar_borrador(self, borrador, referencia=None) -> None:
        referencia = self.original if referencia is None else referencia
        if (borrador.ancho != self.ancho or borrador.alto != self.alto
                or borrador.puntos_pendientes
                or borrador.next_c_number < self.original.next_c_number
                or set(borrador.vision_zone_ids) != set(borrador.zonas)
                or len(set(borrador.vision_zone_ids.values())) != len(borrador.vision_zone_ids)):
            raise ValueError("El borrador debe conservar dimensiones y UUID unicos.")
        for etiqueta, zona in borrador.zonas.items():
            if zona.identifier != etiqueta:
                raise ValueError("La identidad del poligono no coincide con su etiqueta.")
            if (etiqueta in referencia.vision_zone_ids
                    and borrador.vision_zone_ids.get(etiqueta) != referencia.vision_zone_ids[etiqueta]):
                raise ValueError(f"La zona {etiqueta} debe conservar su visionZoneId.")
            ParkingZone(etiqueta, zona.polygon)

    def fuente_vigente(self, capturador, max_edad: float) -> bool:
        reciente = capturador.instantanea()
        self.actualizar_fuente(reciente, max_edad)
        return self.fuente_valida

    def preparar_guardado(self, capturador, max_edad: float) -> bool:
        """Comprueba que no se esté moviendo un punto ni revisando una propuesta.

        También exige que la imagen de la cámara siga siendo reciente antes de guardar.
        """
        if self.bloqueado or self.propuesta is not None or self.control.arrastre is not None:
            self.control.mensaje = "Termine la revision o el arrastre antes de guardar."
            return False
        reciente = capturador.instantanea()
        self.actualizar_fuente(reciente, max_edad)
        if not self.fuente_valida:
            self.control.mensaje = "Fuente no verificable; no se guardo."
            return False
        resultado = []
        try:
            self._validar_borrador(self.borrador)
            aplicado = capturador.aplicar_si_vigente(
                reciente, max_edad, lambda: resultado.append(True), misma_revision=True,
            )
        except (OSError, ValueError, TypeError) as error:
            self.control.mensaje = f"No se guardo: {error}"
            return False
        if not aplicado:
            self.control.mensaje = "La fuente cambio durante la comprobacion; intente de nuevo."
            return False
        return bool(resultado)

    def guardar_con_asociaciones(self, cajones_por_zona: dict[str, str]) -> None:
        """Guarda el cajón correspondiente a cada zona y comprueba el archivo antes de usarlo."""
        self._validar_borrador(self.borrador)
        if set(cajones_por_zona) != set(self.borrador.zonas):
            raise ValueError("Las asociaciones Java no coinciden con las zonas del borrador.")
        atributos = {
            etiqueta: copy.deepcopy(self.atributos.get(etiqueta, {}))
            for etiqueta in self.borrador.zonas
        }
        for etiqueta, cajon_id in cajones_por_zona.items():
            atributos[etiqueta]["cajonId"] = cajon_id
        borrador = copy.deepcopy(self.borrador)
        borrador.metadata["fuente_sha256"] = identidad_fuente(self.tipo, self.fuente)
        guardada = self._guardar_par(borrador, atributos, actualizar_vinculo=False)
        self.original = copy.deepcopy(guardada)
        self.atributos = atributos
        self._usar_borrador(guardada)
        self.control.mensaje = "Calibracion sincronizada y guardada."

    def _guardar_par(self, borrador, atributos, *, actualizar_vinculo: bool):
        try:
            guardado, respaldo = preparar_guardado_calibracion(
                self.ruta, tipo=self.tipo, fuente=self.fuente,
                ancho=self.ancho, alto=self.alto, exigir_respaldo=True,
            )
        except RuntimeError as error:
            self.bloqueado = True
            raise ValueError("No se pudo cancelar el guardado pendiente.") from error
        try:
            try:
                _comprobar_guardado_propio(self.ruta, guardado)
                guardar_calibracion(self.ruta, borrador, self.tipo, atributos_por_zona=atributos)
                if actualizar_vinculo:
                    _comprobar_guardado_propio(self.ruta, guardado)
                    guardar_vinculo(self.ruta, self.tipo, self.fuente, self.ancho, self.alto)
                vinculo = json.loads(ruta_vinculo(self.ruta).read_text(encoding="utf-8"))
                if not _sidecar_compatible(
                    self.ruta, vinculo, self.tipo, self.fuente, self.ancho, self.alto,
                ):
                    raise ValueError("El vinculo guardado no corresponde a la calibracion.")
                contenido = self.ruta.read_bytes()
                guardada = _cargar_copia_guardado(self.ruta, contenido, self.ancho, self.alto)
                datos = json.loads(contenido)
                if (_identidades_y_atributos(datos, guardada) != atributos
                        or not _misma_geometria_e_identidades(guardada, borrador)):
                    raise ValueError("La calibracion guardada no coincide con el borrador.")
            except BaseException as error:
                try:
                    _comprobar_guardado_propio(self.ruta, guardado)
                    _restaurar_json(self.ruta, respaldo)
                    vinculo = json.loads(ruta_vinculo(self.ruta).read_text(encoding="utf-8"))
                    if not _sidecar_compatible(
                        self.ruta, vinculo, self.tipo, self.fuente, self.ancho, self.alto,
                    ):
                        raise ValueError("El vinculo restaurado no corresponde a la calibracion.")
                    finalizar_guardado_pendiente(self.ruta, guardado)
                except BaseException as recuperacion:
                    self.bloqueado = True
                    raise ValueError(
                        f"No se recupero el par anterior; respaldo disponible en {respaldo}."
                    ) from recuperacion
                if not isinstance(error, (OSError, ValueError, TypeError)):
                    raise
                raise _ErrorGuardadoRecuperado(
                    "Se recupero la calibracion anterior tras el error de guardado."
                ) from error
            try:
                finalizar_guardado_pendiente(self.ruta, guardado)
            except BaseException as cierre:
                self.bloqueado = True
                raise ValueError(
                    f"No se pudo cerrar el guardado pendiente; respaldo disponible en {respaldo}."
                ) from cierre
            return guardada
        finally:
            guardado.cerrar()

    def guardar(self, capturador, max_edad: float) -> str | None:
        """Conserva una copia anterior y comprueba el archivo guardado.

        Si algo falla, intenta restaurar la copia antes de devolver el error.
        """
        try:
            verificar_sin_guardado_pendiente(self.ruta)
        except ValueError as error:
            self.bloqueado = True
            self.control.mensaje = str(error)
            return None
        if not self.preparar_guardado(capturador, max_edad):
            return None
        if _misma_geometria_e_identidades(self.borrador, self.original):
            try:
                verificar_sin_guardado_pendiente(self.ruta)
            except ValueError as error:
                self.bloqueado = True
                self.control.mensaje = str(error)
                return None
            return "sin_cambios"
        try:
            borrador = copy.deepcopy(self.borrador)
            borrador.metadata["fuente_sha256"] = identidad_fuente(self.tipo, self.fuente)
            atributos = {
                etiqueta: copy.deepcopy(self.atributos.get(etiqueta, {}))
                for etiqueta in borrador.zonas
            }
            guardada = self._guardar_par(borrador, atributos, actualizar_vinculo=True)
        except _ErrorGuardadoRecuperado as error:
            self.control.mensaje = str(error)
            return None
        except (OSError, ValueError, TypeError) as error:
            if self.bloqueado:
                raise
            self.control.mensaje = f"No se guardo: {error}"
            return None
        self.original = copy.deepcopy(guardada)
        self.atributos = atributos
        self._usar_borrador(copy.deepcopy(guardada))
        return "guardada"
