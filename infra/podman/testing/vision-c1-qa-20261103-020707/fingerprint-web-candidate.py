from hashlib import sha256
import json
from pathlib import Path


raiz = Path('/mnt/new-volume/SmartParking')
qa = raiz / 'infra/podman/testing/vision-c1-qa-20261103-020707'
origen = raiz / 'apps/web'
copia = qa / 'web-source-candidate'
excluir = {
    '.git',
    '.nuxt',
    '.output',
    'dist',
    'node_modules',
    '.pnpm-store',
    'test-results',
    'playwright-report',
    'private',
}
solo_qa = {'tests/browser/vision-c1-monitor.spec.ts'}


def archivos(root):
    resultado = {}
    for archivo in sorted(root.rglob('*')):
        if not archivo.is_file() or archivo.is_symlink():
            continue
        relativo = archivo.relative_to(root).as_posix()
        partes = Path(relativo).parts
        if any(parte in excluir for parte in partes):
            continue
        if any(parte == '.env' or parte.startswith('.env.') for parte in partes):
            continue
        resultado[relativo] = archivo
    return resultado


def hash_arbol(mapa):
    acumulado = sha256()
    lineas = []
    for relativo, archivo in sorted(mapa.items()):
        digest = sha256(archivo.read_bytes()).hexdigest()
        linea = f'{digest}  {relativo}'
        lineas.append(linea)
        acumulado.update((linea + '\n').encode('utf-8'))
    return acumulado.hexdigest(), lineas


archivos_copia = archivos(copia)
archivos_origen = archivos(origen)
hash_copia, lineas = hash_arbol(archivos_copia)
hash_app_server, _ = hash_arbol({
    ruta: archivo
    for ruta, archivo in archivos_copia.items()
    if ruta.startswith('app/') or ruta.startswith('server/')
})
diferencias = []
for ruta, archivo in archivos_copia.items():
    if ruta in solo_qa:
        continue
    fuente = archivos_origen.get(ruta)
    if fuente is None or sha256(archivo.read_bytes()).digest() != sha256(fuente.read_bytes()).digest():
        diferencias.append(ruta)
faltantes = sorted(set(archivos_origen) - set(archivos_copia) - solo_qa)

(qa / 'web-source-candidate.sha256').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
resumen = {
    'archivos_copia': len(archivos_copia),
    'archivos_origen': len(archivos_origen),
    'archivos_solo_qa': sorted(solo_qa & set(archivos_copia)),
    'diferencias_con_origen': diferencias,
    'faltantes_en_copia': faltantes,
    'sha256_arbol': hash_copia,
    'archivos_app_server': sum(
        ruta.startswith('app/') or ruta.startswith('server/')
        for ruta in archivos_copia
    ),
    'sha256_app_server': hash_app_server,
}
(qa / 'web-source-candidate.fingerprint.json').write_text(
    json.dumps(resumen, ensure_ascii=False, indent=2) + '\n',
    encoding='utf-8',
)
print(json.dumps(resumen, ensure_ascii=False))
