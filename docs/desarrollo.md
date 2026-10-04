# Desarrollo local

## Primer inicio

1. Copia `.env.example` como `.env` (`Copy-Item .env.example .env` en PowerShell).
2. Elige una contrasena local de PostgreSQL en `POSTGRES_PASSWORD`; es obligatoria para una base nueva.
3. Conserva `CORREO_TRANSPORTE="consola"` para desarrollo normal. Los campos SMTP pueden quedar vacios.
4. Desde la raiz del proyecto, inicia los servicios:

   ```powershell
   $root = (Resolve-Path .).Path
   podman compose --env-file "$root\.env" --project-directory "$root" -f "$root\infra\compose.dev.yml" up --detach --wait
   ```

5. Comprueba la API con `Invoke-RestMethod http://localhost:8000/health` y abre `http://localhost:3000`.

## Transporte de correo

- `CORREO_TRANSPORTE="consola"` imprime la salida de desarrollo y no requiere credenciales SMTP.
- `CORREO_TRANSPORTE="smtp"` requiere `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, un puerto y un tiempo de espera validos. `SMTP_SECURITY` admite `ssl` o `starttls`.

## Propiedad de configuracion

- `.env` guarda valores locales; `.env.example` es la plantilla segura.
- Compose administra servicios, red, puertos y volumenes.
- FastAPI valida los valores tipados al iniciar.
- `NUXT_API_INTERNAL_BASE_URL` es configuracion privada del servidor Nuxt.

## Equipo nuevo

Clona el repositorio, copia `.env.example` a `.env`, establece una contrasena local y deja el transporte en consola. Inicia el stack con el comando explicito anterior y verifica `/health` antes de usar la Web.

## Windows + WSL + Podman

### Version y configuracion de Podman

Se requiere Podman `>= 6.1.1` en Windows y en la Podman Machine. El entorno verificado usa cliente y servidor `6.1.2`.

Comprueba las versiones y el estado de las maquinas:

```powershell
podman version --format "{{.Client.Version}} | {{.Server.Version}}"
podman machine list
```

La maquina Podman debe tener `force_port_listen = true` dentro de `[engine]` en `/etc/containers/containers.conf`. Verifica el archivo de la maquina existente (sustituye su nombre si no es `podman-machine-default`):

```powershell
podman machine ssh podman-machine-default "grep -n -E '^\[engine\]|force_port_listen' /etc/containers/containers.conf"
```

Para configurar el ajuste, abre una sesion en esa maquina y edita el archivo con `sudoedit /etc/containers/containers.conf`. Conserva los demas ajustes; agrega la clave dentro de la seccion `[engine]` existente, o agrega una sola seccion si aun no existe. No reemplaces el archivo completo desde el proyecto.

```toml
[engine]
force_port_listen = true
```

### URLs y publicaciones del host

| Servicio | URL desde Windows | Publicacion del host |
|---|---|---|
| Web | `http://localhost:3000` | `127.0.0.1:3000` |
| API (health) | `http://localhost:8000/health` | `127.0.0.1:8000` |

Las publicaciones usan intencionalmente loopback para que Web y API no queden expuestos en todas las interfaces de red de Windows. Compose mantiene los listeners dentro de los contenedores en `0.0.0.0`: Nuxt en `0.0.0.0:3000` y FastAPI en `0.0.0.0:8000`. El binding de host `127.0.0.1:3000` no significa que Nuxt deba escuchar en `127.0.0.1` dentro del contenedor. Nuxt se comunica con FastAPI por el DNS interno `http://api-dev:8000`.

Cambiar la publicacion a `0.0.0.0` vuelve a exponer el servicio en las interfaces del host y requiere revalidar el forwarding de localhost entre Windows, WSL y Podman.

### Comprobacion rapida

Desde la raiz del repositorio, el helper solo consulta la pagina Web y el health de la API; no inicia ni modifica contenedores:

```powershell
.\scripts\verificar-desarrollo.bat
```

Desde Linux/WSL tambien se puede ejecutar su par de shell:

```bash
bash scripts/verificar-desarrollo.sh
```
