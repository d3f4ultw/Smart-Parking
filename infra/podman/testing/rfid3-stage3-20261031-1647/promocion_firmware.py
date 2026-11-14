"""Promueve y recupera archivos ESP32 sin confiar en operaciones inciertas."""


def comprobar_preparacion(remoto, archivos, nuevo, original):
    """Exige destinos, originales y candidatos exactamente conocidos."""
    for nombre, (antes, despues) in archivos.items():
        if antes is not None and antes == despues:
            raise RuntimeError("La promoción no admite archivos sin cambios.")
        destino = nombre
        candidato = nuevo + "/" + nombre
        respaldo = original + "/" + nombre
        if remoto.existe(respaldo):
            raise RuntimeError("Ya existe un respaldo remoto de promoción.")
        if not remoto.existe(candidato) or remoto.sha256_remoto(candidato) != despues:
            raise RuntimeError("Candidato remoto ausente o alterado.")
        if antes is None:
            if remoto.existe(destino):
                raise RuntimeError("El archivo nuevo ya existe en el ESP32.")
        elif not remoto.existe(destino) or remoto.sha256_remoto(destino) != antes:
            raise RuntimeError("El archivo instalado difiere del snapshot.")


def promover(remoto, archivos, nuevo, original):
    """Instala únicamente los bytes comprobados y conserva cada original."""
    comprobar_preparacion(remoto, archivos, nuevo, original)
    for nombre, (antes, despues) in archivos.items():
        destino = nombre
        if antes is not None:
            remoto.renombrar(destino, original + "/" + nombre)
        remoto.renombrar(nuevo + "/" + nombre, destino)
        if remoto.sha256_remoto(destino) != despues:
            raise RuntimeError("Falló la lectura de vuelta del candidato.")


def recuperar(remoto, archivos, original):
    """Reconcilia por hashes incluso si se perdió el resultado de un rename."""
    if any(antes is not None and antes == despues for antes, despues in archivos.values()):
        raise RuntimeError("La recuperación no admite archivos sin cambios.")
    for nombre, (antes, despues) in reversed(tuple(archivos.items())):
        respaldo = original + "/" + nombre
        existe_destino = remoto.existe(nombre)
        existe_respaldo = remoto.existe(respaldo)
        if existe_respaldo and (antes is None or remoto.sha256_remoto(respaldo) != antes):
            raise RuntimeError("El respaldo remoto tiene bytes inesperados.")
        if existe_destino:
            huella = remoto.sha256_remoto(nombre)
            if huella == despues:
                if antes is not None and not existe_respaldo:
                    raise RuntimeError("Falta el original del archivo promovido.")
                remoto.eliminar(nombre)
                existe_destino = False
            elif antes is not None and huella == antes and not existe_respaldo:
                continue
            else:
                raise RuntimeError("El destino remoto tiene bytes inesperados.")
        if antes is not None:
            if existe_destino or not existe_respaldo:
                raise RuntimeError("No se puede recuperar el original de forma segura.")
            remoto.renombrar(respaldo, nombre)
            if remoto.sha256_remoto(nombre) != antes:
                raise RuntimeError("El original restaurado no coincide.")
        elif remoto.existe(nombre):
            raise RuntimeError("El archivo nuevo no se retiró durante recuperación.")
