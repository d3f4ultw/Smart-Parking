"""Inicia el programa salvo cuando la placa está en modo de mantenimiento."""

try:
    archivo = open("maintenance.flag", "r")
    archivo.close()
except OSError:
    import aplicacion

    aplicacion.main()
else:
    print("MAINTENANCE,REPL")
