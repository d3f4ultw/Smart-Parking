"""Arranca el firmware salvo cuando se solicitó acceso de mantenimiento."""

try:
    archivo = open("maintenance.flag", "r")
    archivo.close()
except OSError:
    import esp32_test

    esp32_test.main()
else:
    print("MAINTENANCE,REPL")
