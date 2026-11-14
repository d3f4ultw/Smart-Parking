/** Rutas y acciones que el servidor web puede enviar al servidor Java;
 * cada entrada indica el tipo de solicitud y lo que debe hacer.
 */
export const ALLOWLIST = new Map([
  ['GET /api/v1/csrf', 'csrf'],
  ['GET /api/v1/sesion', 'sesion'],
  ['POST /api/v1/sesion', 'sesion'],
  ['DELETE /api/v1/sesion', 'sesion'],
  ['GET /api/v1/clientes/csrf', 'cliente-csrf'],
  ['POST /api/v1/clientes/registro', 'cliente-registro'],
  ['GET /api/v1/clientes/sesion', 'cliente-sesion'],
  ['POST /api/v1/clientes/sesion', 'cliente-sesion'],
  ['DELETE /api/v1/clientes/sesion', 'cliente-sesion'],
  ['GET /api/v1/clientes/portal', 'cliente-portal'],
  ['GET /api/v1/clientes/administracion', 'administracion-clientes'],
  ['GET /api/v1/accesos/historial', 'historial-accesos'],
  ['GET /api/v1/accesos/capacidad', 'capacidad-rfid'],
  ['GET /api/v1/accesos/dentro', 'entradas-activas'],
  ['GET /api/v1/accesos/salidas-manuales/capacidad', 'salida-manual-capacidad'],
  ['GET /api/v1/vision/cajones', 'vision-cajones'],
  ['POST /api/v1/clientes/membresia/checkout', 'cliente-checkout'],
  ['PATCH /api/v1/clientes/contrasena', 'cliente-contrasena'],
  ['GET /api/v1/panel', 'panel'],
  ['GET /api/v1/empleados', 'empleados'],
  ['POST /api/v1/empleados', 'crear-empleado'],
  ['GET /api/v1/operadores', 'operadores'],
  ['POST /api/v1/operadores', 'crear-operador'],
  ['POST /api/v1/operadores/activacion/validar', 'validar-operador'],
  ['POST /api/v1/operadores/activacion/completar', 'activar-operador'],
  ['POST /api/v1/operadores/recuperacion/validar', 'validar-recuperacion'],
  ['POST /api/v1/operadores/recuperacion/completar', 'completar-recuperacion'],
  ['GET /api/v1/eventos/administracion', 'eventos'],
  ['POST /api/v1/eventos/administracion/heartbeat', 'eventos-heartbeat'],
])

/** Filtros que puede llevar cada consulta, como página, búsqueda o fechas;
 * cualquier otro filtro se rechaza antes de enviarla al servidor Java.
 */
export const CONSULTAS = new Map([
  ['empleados', ['pagina', 'busqueda', 'soloElegiblesOperador']],
  ['operadores', ['pagina', 'busqueda', 'estado']],
  ['administracion-clientes', ['pagina', 'estado', 'busqueda']],
  ['historial-accesos', ['pagina', 'lector', 'resultado', 'periodo', 'desde', 'hasta']],
  ['entradas-activas', ['pagina', 'busqueda']],
  ['eventos', ['despues']],
])
