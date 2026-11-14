package mx.smartparking.api.operadores;

/** Indica qué estados se pueden elegir al buscar cuentas de operador. */
public enum EstadoFiltroOperador {
    TODOS,
    PENDIENTE,
    ACTIVA,
    INACTIVA;

    /** Indica qué estado de cuenta corresponde al filtro elegido para buscar operadores. */
    public EstadoCuentaOperador estadoCuenta() {
        return this == TODOS ? null : EstadoCuentaOperador.valueOf(name());
    }
}
