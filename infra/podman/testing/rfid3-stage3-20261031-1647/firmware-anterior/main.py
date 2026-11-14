"""Inicia el firmware modular sin perder el REPL de mantenimiento."""

try:
    archivo = open("maintenance.flag", "r")
    archivo.close()
except OSError:
    import aplicacion

    aplicacion.main()
else:
    print("MAINTENANCE,REPL")
