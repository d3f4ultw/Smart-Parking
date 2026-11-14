from hashlib import sha256
from pathlib import Path


raiz = Path('/mnt/new-volume/SmartParking')
qa = raiz / 'infra/podman/testing/vision-c1-qa-20261103-020707'
pares = (
    ('api-source', raiz / 'services/api'),
    ('web-source', raiz / 'apps/web'),
)
solo_qa = {'tests/browser/vision-c1-monitor.spec.ts'}
lineas = []
diferencias = []
conteos = {}

for copia, original in pares:
    carpeta = qa / copia
    archivos = sorted(path for path in carpeta.rglob('*') if path.is_file())
    conteos[copia] = len(archivos)
    for archivo in archivos:
        relativo = archivo.relative_to(carpeta).as_posix()
        digest = sha256(archivo.read_bytes()).hexdigest()
        lineas.append(f'{digest}  {copia}/{relativo}')
        if copia == 'web-source' and relativo in solo_qa:
            continue
        fuente = original / relativo
        if not fuente.is_file() or sha256(fuente.read_bytes()).hexdigest() != digest:
            diferencias.append(f'{copia}/{relativo}')

(qa / 'snapshot-final.sha256').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
print(f'archivos={conteos}; diferencias_fuente_actual={len(diferencias)}')
for diferencia in diferencias:
    print(f'DIFERENCIA {diferencia}')
