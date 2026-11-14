"""Permite editar las zonas y relacionarlas con los cajones del estacionamiento."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from aplicacion_local import EditorLocal, validar_archivo_local
from estado_calibracion import activaciones_pendientes
from publicador_java import PublicadorVision, cargar_configuracion
from temporal_validation import load_zones


class EdicionPermanente:
    """Ayuda a editar las zonas y conservar qué cajón corresponde a cada una."""

    def __init__(self, args, identidad):
        self.args = args
        self.identidad = identidad
        self.editor = None
        self.permitir_publicar = False
        self.mensaje = ""
        self.configuracion = None
        self.paso_pendiente = None
        self.cajones_pendientes = None

    @property
    def activa(self):
        return self.editor is not None

    def iniciar(self, capturador, max_edad):
        """Abre la edición si la cámara y las zonas están disponibles.

        También requiere los datos necesarios para comunicarse con el sistema.
        """
        anterior = getattr(self.args, "publicador", None)
        self.permitir_publicar = anterior is not None and not anterior.rechazada
        self.configuracion = (
            getattr(anterior, "config", None)
            or getattr(self.args, "configuracion_vision", None)
        )
        if self.configuracion is None:
            self.mensaje = "Publicacion Java no disponible; no se abrio la calibracion."
            return False
        try:
            if (not self.args.seleccion_segura
                    or activaciones_pendientes(self.args.ruta_productiva.parent)):
                raise ValueError("La calibracion activa requiere una seleccion segura.")
            muestra = capturador.instantanea()
            if muestra.cuadro is None or muestra.estado != "conectada" or muestra.momento is None:
                raise ValueError("La fuente no esta disponible para calibrar.")
            dimensiones = muestra.cuadro.shape[:2]
            validar_archivo_local(
                self.args.zones, self.args.source, self.identidad, dimensiones, recuperar=False,
            )
            creados = []
            aceptado = capturador.aplicar_si_vigente(
                muestra,
                max_edad,
                lambda: creados.append(
                    EditorLocal(self.args.zones, self.args.source, self.identidad,
                                muestra, recuperar=False)
                ),
            )
            if not aceptado:
                raise ValueError("La fuente cambio; vuelva a iniciar calibracion.")
            self.editor = creados[0]
            self.editor.control.mensaje = "Edite el mapa activo; S lo sincroniza con Java."
            return True
        except (OSError, TypeError, ValueError) as error:
            self.mensaje = str(error)
            self._reanudar()
            return False

    def _reanudar(self):
        if (not self.permitir_publicar or not self.args.seleccion_segura
                or self.args.publicador is not None
                or activaciones_pendientes(self.args.ruta_productiva.parent)):
            return
        try:
            validar_archivo_local(self.args.zones, self.args.source, self.identidad, recuperar=False)
            zonas = load_zones(self.args.zones)
            config = cargar_configuracion(self.args.zones, zonas)
            if config is None:
                return
            self.configuracion = config
            nuevo = PublicadorVision(config, iniciada_en=datetime.now(timezone.utc))
            nuevo.iniciar()
            self.args.configuracion_vision = config
            self.args.publicador = nuevo
        except (OSError, ValueError):
            self.args.configuracion_vision = None
            self.mensaje = "Publicacion detenida: no se pudo reanudar la calibracion activa."
            print(self.mensaje, flush=True)

    def cerrar(self):
        """Mantiene abierta la edición si queda un cambio pendiente.

        En caso contrario la cierra e intenta reanudar los envíos cuando las
        condiciones lo permiten.
        """
        if self.paso_pendiente is not None:
            self.permitir_publicar = False
            if self.editor is not None:
                self.editor.control.mensaje = (
                    "Java ya acepto el mapa; pulse S para completar la sincronizacion."
                )
            return False
        self.editor = None
        self._reanudar()
        self.permitir_publicar = False
        self.configuracion = None
        self.paso_pendiente = None
        self.cajones_pendientes = None
        return True

    def pantalla(self):
        return self.editor.pantalla()

    def tecla(self, tecla, capturador, max_edad):
        """Al guardar, envía las zonas al sistema y después las guarda en este equipo.

        Si falla una consulta o el guardado, conserva lo pendiente para reintentarlo
        sin repetir los cambios que el sistema ya aceptó.
        """
        if self.editor is None:
            return None
        if self.paso_pendiente == "get":
            if tecla in (ord("s"), ord("S")):
                return self._consultar_y_guardar(capturador, max_edad)
            self.editor.control.mensaje = (
                "Java ya acepto el mapa; pulse S para completar la sincronizacion."
            )
            return None
        if self.paso_pendiente == "local":
            if tecla in (ord("s"), ord("S")):
                return self._guardar_local(capturador, max_edad)
            self.editor.control.mensaje = (
                "Java ya acepto el mapa; pulse S para completar la sincronizacion."
            )
            return None

        accion = self.editor.tecla(tecla)
        if accion == "cancelar":
            self.cerrar()
            return "cancelada"
        if accion != "guardar":
            return None
        if not self.editor.preparar_guardado(capturador, max_edad):
            return None
        anterior = getattr(self.args, "publicador", None)
        if anterior is not None:
            if not anterior.detener():
                self.editor.control.mensaje = (
                    "No se pudo drenar la publicacion; intente guardar de nuevo."
                )
                return None
            self.args.publicador = None
        zonas = []
        for etiqueta in self.editor.borrador.zonas:
            atributos = self.editor.atributos.get(etiqueta, {})
            zonas.append({
                "visionZoneId": str(self.editor.borrador.vision_zone_ids[etiqueta]),
                "etiqueta": etiqueta,
                "cajonId": atributos.get("cajonId"),
            })
        try:
            codigo = self._cliente_calibracion().activar_calibracion(zonas)
        except (OSError, ValueError) as error:
            self.editor.control.mensaje = f"No se sincronizo con Java: {error}"
            return None
        if codigo != 204:
            self.editor.control.mensaje = f"Java rechazo el mapa (HTTP {codigo}); corrige o cancela."
            return None
        self.paso_pendiente = "get"
        self.editor.bloqueado = True
        self.editor.control.mensaje = "Java acepto el mapa; consultando cajones asignados."
        return self._consultar_y_guardar(capturador, max_edad)

    def _cliente_calibracion(self):
        if self.configuracion is None:
            raise ValueError("No hay configuracion Vision disponible.")
        return PublicadorVision(self.configuracion)

    def _consultar_y_guardar(self, capturador, max_edad):
        """Consulta qué cajón corresponde a cada zona y continúa el guardado en este equipo."""
        try:
            respuesta = self._cliente_calibracion().consultar_calibracion()
            self.cajones_pendientes = self._asociaciones_de(respuesta)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.editor.control.mensaje = (
                f"Java acepto el mapa, pero no se pudo consultar: {error}. Pulse S para reintentar."
            )
            return None
        self.paso_pendiente = "local"
        return self._guardar_local(capturador, max_edad)

    def _asociaciones_de(self, respuesta):
        filas = respuesta.get("zonas")
        if not isinstance(filas, list):
            raise ValueError("la respuesta no incluye las zonas")
        esperadas = {
            str(identidad): etiqueta
            for etiqueta, identidad in self.editor.borrador.vision_zone_ids.items()
        }
        obtenidas = {}
        for fila in filas:
            if not isinstance(fila, dict):
                raise ValueError("una asociacion de zona es invalida")
            try:
                identidad = str(UUID(fila["visionZoneId"]))
                cajon = str(UUID(fila["cajonId"]))
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise ValueError("Java devolvio una identidad de cajon invalida") from error
            etiqueta = esperadas.get(identidad)
            if etiqueta is None or fila.get("etiqueta") != etiqueta or identidad in obtenidas:
                raise ValueError("Java devolvio asociaciones distintas del borrador")
            obtenidas[identidad] = cajon
        if set(obtenidas) != set(esperadas):
            raise ValueError("Java no devolvio todas las asociaciones activas")
        return {esperadas[identidad]: cajon for identidad, cajon in obtenidas.items()}

    def _guardar_local(self, capturador, max_edad):
        """Guarda las relaciones entre zonas y cajones si la imagen de la cámara sigue vigente."""
        if not self.editor.fuente_vigente(capturador, max_edad):
            self.editor.control.mensaje = (
                "Java acepto el mapa; la fuente no esta vigente para guardarlo localmente."
            )
            return None
        try:
            self.editor.guardar_con_asociaciones(self.cajones_pendientes)
            self.configuracion = cargar_configuracion(
                self.args.zones, load_zones(self.args.zones),
            )
        except (OSError, ValueError, TypeError) as error:
            self.editor.control.mensaje = (
                f"Java acepto el mapa, pero no se guardo localmente: {error}. Pulse S para reintentar."
            )
            return None
        self.paso_pendiente = None
        self.args.configuracion_vision = self.configuracion
        self.permitir_publicar = self.configuracion is not None
        self.cerrar()
        return "actualizar"
