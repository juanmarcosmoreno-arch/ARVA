# Plan: Flye nativo en macOS desde ARVA.app

Punto 32 del registro de la prueba en la Mac (`docs/registro-prueba-mac.md`). Fecha de las comprobaciones:
2026-11-04. Se eligió la opción (b); el lado del servidor (lock osx-arm64, adaptador, API, worker y web) está hecho y
su contrato está en **"Contrato implementado"** (al final de la sección 3). La parte de ARVA.app en Swift y el trabajo
de CI en `macos-15` están escritos (**"Lado de ARVA.app"**, 2026-11-06) pero **sin compilar todavía**: se escribieron
en Linux; el primer push a la rama los compila y prueba en GitHub Actions (`mac-app.yml`).

El mismo ejecutor corre también **Bakta** desde el 2026-11-06 (punto 49 del registro: el bloque de DIAMOND con la base
completa no entra en Docker): ver **"Bakta nativo"** al final del documento.

## El problema, en una línea

Flye 2.9.6 reserva y llena con ceros una tabla fija de 8 GiB al contar k-mers, sea cual sea el tamaño de los datos.
Dentro de la VM Linux de Docker Desktop, en una Mac de 8 GB, eso no entra (pico medido 8,8 GB, punto 29); en macOS
nativo sí corre, porque macOS comprime esas páginas casi vacías (el usuario corrió Flye 2.9.6 nativo en la misma
Mac).

Fuente (código de Flye en la etiqueta `2.9.6`, `src/sequence/vertex_index.cpp`):

- `VertexIndex::countKmers()` llama siempre `_kmerCounter.count(/*use flat counter*/ true)` (líneas 19-22);
- `KmerCounter::count` (líneas 363-381): `COUNTER_LEN = std::pow(4, kmerSize) / 2` con el comentario "in case of
  k=17, takes 8Gb", luego `new std::atomic<uint8_t>[COUNTER_LEN]` y `std::memset(_flatCounter, 0, COUNTER_LEN)`.

No hay opción de línea de comandos que lo evite, y cambiar el código de Flye queda descartado (sería otra
herramienta, no Flye 2.9.6).

## 1. Hechos comprobados

### Flye 2.9.6 para osx-arm64 en Bioconda: existe

Fuentes: `https://conda.anaconda.org/bioconda/osx-arm64/repodata.json` (leído 2026-11-04) y la lista de archivos de
`https://api.anaconda.org/package/bioconda/flye/files`.

| Archivo (osx-arm64) | sha256 | md5 | Tamaño |
|---|---|---|---|
| `flye-2.9.6-py313h05f0e27_1.conda` | `74a38467a2a1a6d6fa62aad6aef1c632055bd8ad5b24790db8526e7cad93b318` | `e848ddf7715bbd7796ea6611ba5b40b2` | 23.854.844 B |

- Dependencias declaradas: `libcxx >=19`, `libzlib >=1.3.2,<2.0a0`, `python >=3.13,<3.14.0a0`,
  `python_abi 3.13.* *_cp313`, `setuptools`. Licencia BSD-3-Clause.
- Es la misma tanda que usa ARVA en Linux: compilación `_1` del 2026-04-13 (subida 05:14 UTC), igual que
  `linux-64/flye-2.9.6-py313h7fbb527_1` y `linux-aarch64/flye-2.9.6-py313h30571f8_1` de
  `docker/conda-locks/flye/`. También hay variantes py310, py311 y py312 (`_1`) y una tanda anterior `_0` (2025-05-06,
  `.tar.bz2`, py39-py312). Hay builds osx-64 (Intel) de la misma tanda.

### El mismo mecanismo de locks puede producir un lock osx-arm64

Hoy (`scripts/conda_locks.py`, `scripts/install-micromamba.sh`): un lock explícito por plataforma con la URL exacta
de cada paquete y `#sha256:`, resuelto con `micromamba create --dry-run --json --platform <p>
--override-channels --strict-channel-priority -c conda-forge -c bioconda <spec>`; micromamba rechaza una descarga cuyo
checksum no coincide y no resuelve nada al instalar desde el lock.

Prueba hecha (solo metadatos, sin descargar ni ejecutar ningún binario de macOS): ese mismo comando con el
micromamba 2.9.0 linux-64 de ARVA y `--platform osx-arm64`:

- **sin más, falla**: `nothing provides __osx >=11.0 needed by libcxx-18.1.8-h167917d_0`; micromamba sugiere
  `CONDA_OVERRIDE_OSX`;
- **con `CONDA_OVERRIDE_OSX=11.0` resuelve**: 19 paquetes, 48,0 MB de descarga, terminando en
  `bioconda/osx-arm64/flye-2.9.6-py313h05f0e27_1.conda#sha256:74a38467…b318` (el mismo sha256 que el repodata).
  macOS 11 es el mínimo que exigen `libcxx`, `libzlib` y `python`; ARVA.app ya exige macOS 13
  (`LSMinimumSystemVersion` en `apps/mac/ARVA/Info.plist`).

<details>
<summary>Lock osx-arm64 que resultaría (dry-run del 2026-11-04, no guardado como archivo)</summary>

```
@EXPLICIT
https://conda.anaconda.org/conda-forge/noarch/python_abi-3.13-9_cp313.conda#sha256:9dc0cb6a20ebc7e9bcd8c6868f2bec083c114b0ba20b7118405c036533d5c522
https://conda.anaconda.org/conda-forge/noarch/tzdata-2026e-h5d301ff_0.conda#sha256:2b7ca858879f183ce2dcc65b300f48a0133d5430550f35b23d80d405a0788dbf
https://conda.anaconda.org/conda-forge/noarch/ca-certificates-2026.10.23-hbd8a1cb_0.conda#sha256:95619b9c1184be7175392eeb0ee7eeb5ccf25d280951f4225f2d62e725790be3
https://conda.anaconda.org/conda-forge/osx-arm64/libcxx-23.1.4-h55c6f16_2.conda#sha256:9c390b4f403db32346754ccef6b84b7e5d9b70cb6d76258fd23b05f2db2ab216
https://conda.anaconda.org/conda-forge/osx-arm64/libzlib-1.3.2-h8088a28_3.conda#sha256:a18fa5d5bac452401459f966cf0d872224e8080c4ff93c77e168d43ab42ef9d7
https://conda.anaconda.org/conda-forge/osx-arm64/libpython-3.13.18-h0af5753_100_cp313.conda#sha256:2ccf200438a519589d86acb96c75822f7ba6f6a9e654d1da355521cec4adfac3
https://conda.anaconda.org/conda-forge/osx-arm64/bzip2-1.0.8-h4e30115_10.conda#sha256:8ec22f0ba25cbfc2e64d70cf29459eccd7ffdf6436f6a6ff15bbfef799f7d4f6
https://conda.anaconda.org/conda-forge/osx-arm64/libexpat-2.9.0-h6111c0a_0.conda#sha256:b155c524118f751ad8b1c823397bab8b7f715f7e3ca10479925867a7e23e7e9d
https://conda.anaconda.org/conda-forge/osx-arm64/libffi-3.7.0-h47dc5ef_1.conda#sha256:2783389a7b9dda04c62cc54c6bbeb03dd3cef24b3fc642715d02a3fa19464a9a
https://conda.anaconda.org/conda-forge/osx-arm64/liblzma-5.8.3-h8088a28_1.conda#sha256:23d0630046a3e8b164d8f80f2b74ed2605af2e7050ab9913018056402fae4311
https://conda.anaconda.org/conda-forge/osx-arm64/libmpdec-4.0.0-h84a0fba_2.conda#sha256:04cc136c5a956a73aa14e0a160b5822b0b29714e67b299fa1b1fd16dbcba5366
https://conda.anaconda.org/conda-forge/osx-arm64/ncurses-6.6-he64c551_1.conda#sha256:7024a48c8c0d0114ed4ab53c76bf9275d50e91ba7cea367a9aead638d3c29c68
https://conda.anaconda.org/conda-forge/osx-arm64/openssl-3.6.5-h55eecbc_0.conda#sha256:44fbc526456571a9fb8fa18157f6f269d4d4bd40eef20183a93b9c9296f94497
https://conda.anaconda.org/conda-forge/osx-arm64/tk-8.6.13-hbeba79b_4.conda#sha256:857d89087ae7f2c328cf256728affcb7343031a148b4af847334d248a9cf564c
https://conda.anaconda.org/conda-forge/osx-arm64/libsqlite-3.54.1-h34a968b_101.conda#sha256:c49adf700ad17332b938ac627845a3fdc70a0810660d3ec3814de25b156fbf60
https://conda.anaconda.org/conda-forge/osx-arm64/readline-8.3-h8b90a29_1.conda#sha256:d6782b430e6dce4fe8c7ac118cd988d5a193eb4a7f60741edfaede58016b6110
https://conda.anaconda.org/conda-forge/osx-arm64/python-3.13.18-hb59dee6_100_cp313.conda#sha256:ca7809f986ebd644a418bd52e3bfa1ece8979441917c08e47d341b9e818c652b
https://conda.anaconda.org/conda-forge/noarch/setuptools-84.2.1-pyhe730653_0.conda#sha256:17add609d1a31c874e39a03935072be59bcafb06d42383eceabea746d12e6025
https://conda.anaconda.org/bioconda/osx-arm64/flye-2.9.6-py313h05f0e27_1.conda#sha256:74a38467a2a1a6d6fa62aad6aef1c632055bd8ad5b24790db8526e7cad93b318
```

</details>

### micromamba para macOS arm64: existe

- conda-forge publica `osx-arm64/micromamba-2.9.0-0.tar.bz2` (la misma versión y build que fija
  `scripts/install-micromamba.sh`): sha256 `500f5074feb8d02c4296ef9921c3650ed2874171805a9fbb8fbb53896433646b`, md5
  `7e00485eb3bae373eeb1121859aa3cbc`, 6.648.894 B, depende de `__osx >=11.0` y `libcxx >=19` (consulta
  `micromamba search` a conda-forge, el mismo método que `conda_locks.py verify-micromamba`; md5 igual en
  `api.anaconda.org/package/conda-forge/micromamba/files`).
- La documentación de mamba (`mamba.readthedocs.io`, "Micromamba Installation") da la instalación manual para
  "macOS Silicon/M1 (ARM64)" extrayendo solo `bin/micromamba` del paquete osx-arm64, como hace ARVA en Linux.

### Qué hay que cambiar en los scripts de locks (comprobado leyendo el código)

- `scripts/conda_locks.py`: `PLATFORMS` y la expresión `ALLOWED_URL` solo admiten `linux-64`, `linux-aarch64` y
  `noarch`; `machine_platform()` rechaza todo lo que no sea Linux; `run()` quita del entorno toda variable `CONDA*`,
  así que `update` tiene que poner `CONDA_OVERRIDE_OSX` explícitamente al resolver para osx-arm64; `check` exige un
  lock o una nota `.unavailable` por cada herramienta y plataforma, así que osx-arm64 debe ser una plataforma
  **opcional, solo para Flye** (por ejemplo, un archivo `docker/conda-locks/flye/native-platforms`), no una más de
  la lista.
- `scripts/install-micromamba.sh`: sale con error fuera de Linux y usa `sha256sum` (macOS trae `shasum -a 256`);
  `verify-micromamba` solo busca `SUBDIR="linux-…"`.
- En la Mac del usuario no se puede contar con `python3` del sistema; para verificar el entorno instalado
  (`verify-env`) sirve el propio Python 3.13 del entorno de Flye.

## 2. Arquitecturas posibles

Condición común a las dos: los datos tienen que estar en una **carpeta del Mac** (`--data-dir`, por ejemplo
`/Volumes/JM/ARVA/data`), no en un volumen de Docker, y **sin espacios en la ruta**: Flye convierte las rutas de
lecturas en absolutas (`os.path.abspath`, `flye/main.py` 2.9.6, línea 739) y después, en `_run`, rechaza las que
tienen espacios ("Path to reads contain spaces", línea 461). Dentro del contenedor la ruta es `/data/...`; en la Mac,
`<carpeta de datos>/...`. Entre los dos lados solo viajan **rutas relativas a la carpeta de datos**.

### (a) Ejecutor nativo con puerto local

ARVA.app abre un servidor HTTP en `127.0.0.1:<puerto>` con un token; el worker (en Docker) lo llama vía
`host.docker.internal` (documentado por Docker Desktop: "resolves to the internal IP address of your host") y le pide
correr Flye; el ejecutor valida los parámetros con el mismo adaptador, comprueba que todas las rutas caen dentro de
la carpeta de datos y corre solo Flye.

### (b) ARVA.app pide trabajo a la API (sin puerto de entrada)

ARVA.app, que ya consulta `http://localhost:8080/api/v1/dashboard` cada 60 s para no dejar dormir la Mac
(`SleepGuard.swift`), consulta además cada pocos segundos si hay "trabajos de Flye esperando ejecución nativa", toma
uno con un *lease* (préstamo con vencimiento), lo corre y va informando. El worker sigue dueño del trabajo: prepara
las entradas, espera mirando la base y, al terminar Flye, hace el mismo post-proceso de hoy.

### Comparación

| | (a) puerto en la Mac | (b) la app consulta a la API |
|---|---|---|
| Superficie de ataque | Un servidor HTTP nuevo en Swift (Foundation no trae uno: habría que escribir el parser con Network.framework). Cualquier proceso local y cualquier contenedor pueden llegar al puerto; todo depende del token y de la validación. **No verificado**: si Docker Desktop alcanza un servicio que escucha solo en 127.0.0.1 vía `host.docker.internal`; si hiciera falta escuchar en 0.0.0.0, quedaría expuesto a la red local. | Ningún puerto nuevo: solo un cliente HTTP (`URLSession`, ya usado) hacia `127.0.0.1:8080`, publicado hoy solo en 127.0.0.1 (`docker-compose.yml`). Los endpoints nuevos de la API exigen un token (ver abajo). |
| Qué ejecuta la Mac | Lo que pida la petición, si pasa la validación. | Lo mismo, pero la app nunca recibe argv: recibe parámetros estructurados y arma el argv ella misma con el adaptador. |
| Cancelación | El worker cierra la conexión o llama otro endpoint; la app mata el grupo de procesos. | La respuesta del *heartbeat* dice "cancelar" cuando la API tiene `cancel_requested_at`; la app mata el grupo de procesos (ya existe `Shell.terminate(root:grace:)` con descendientes) y lo informa; el worker sigue por el camino de `JobCancelled` de hoy. |
| Progreso y registro | Hay que transmitirlos por la conexión o por archivos. | Flye escribe `flye.stderr.log` y `flye.log` en la carpeta de resultados compartida; el `_StageMonitor` del worker ya lee ese archivo. No hace falta transmitir nada (**a verificar**: que los cambios de un archivo escrito en la Mac se vean enseguida dentro de la VM). |
| Reanudar | Igual en las dos: la carpeta de trabajo de Flye queda en la carpeta compartida y el mecanismo actual (`_keep_flye_checkpoint`, `read_checkpoint`, `--resume`) sirve sin cambios. Una reanudación debe correr con la misma compilación de Flye (nativa con nativa). | ← |
| Rutas `/data` ↔ Mac | El worker manda rutas; el ejecutor las traduce y verifica. | La API da rutas relativas; la app las une a su `ARVA_DATA_DIR` (de `arva.conf`, que ya lee `ArvaConfig.swift`), resuelve enlaces y rechaza lo que salga de la carpeta. Antes de nada compara el ID de `.arva-storage` con el que da la API, para estar segura de que es la misma carpeta. Los enlaces a las lecturas que crea el worker hoy son absolutos (`/data/...`): deben pasar a ser relativos para resolverse en los dos lados. |
| Mac dormida | Hay que tomar la aserción también durante la llamada. | Sin cambios: el trabajo cuenta como "running" en `jobs_running`, así que `SleepGuard` ya mantiene la Mac despierta. |
| App cerrada | La llamada del worker falla; el ejecutor muere con la app. | El trabajo queda "esperando a ARVA.app"; si se cierra a mitad, el *lease* vence (sin *heartbeat* en ~2 min) y el worker lo trata como "detenido desde afuera": guarda la carpeta para reanudar. Al cerrar, la app ya pregunta si hay análisis activos (`askToStop`); debe además matar a Flye. Si la app se cae, sus hijos **no mueren solos** en macOS: la app guarda el PID en la carpeta del trabajo y, al volver a abrirse, termina un Flye huérfano antes de seguir. |
| Cuentas de usuario activadas | El worker no pasa por la sesión web. | La app no tiene sesión; usa el token, no una cuenta. |

**Recomendación: (b).** No abre ningún puerto, reutiliza lo que ya funciona (cliente HTTP de la app, monitor de
log, checkpoint, cancelación por base de datos, `SleepGuard`) y la app nunca ejecuta un argv que venga de afuera.

### Detalles de (b) que hacen a la seguridad

- **Token**: la app genera uno al azar y lo escribe con permisos 0600 en `~/.config/arva/host/`, la carpeta que el
  lanzador ya monta solo lectura en `/run/arva-host` (`scripts/lib/arva-locations.sh`, montaje `host-facts`); la API
  lo lee de ahí. Los endpoints nativos
  rechazan toda petición sin él. No protege contra un proceso del mismo usuario (que igual podría escribir en la
  carpeta de datos), sí contra páginas web (ya frenadas por `LocalOrigin`) y otros usuarios de la Mac.
- **Una sola herramienta**: la app solo sabe correr Flye desde `~/.arva-tools/conda/flye/bin/flye` (el entorno
  creado desde el lock osx-arm64 y verificado con `verify-env`), sin shell, con argv en lista (`Process`), `cwd` en
  la carpeta de resultados y un entorno limpio como el de `arva_tools.runner` (sin variables con TOKEN, PASSWORD,
  etc.; HOME temporal).
- **El mismo adaptador**: la app trae `arva_tools/flye.py` (con `base.py` y `runner.py`) y lo corre con el Python
  del entorno de Flye (`python -I`): `FlyeParams.validate`, `FlyeAdapter.argv` contra el `--help` del Flye nativo,
  `failure_reason`, `read_checkpoint`. Hoy `arva_tools/__init__.py` importa el registro con todos los adaptadores
  (algunos usan `arva_core`); el módulo nativo debe poder importarse solo con la biblioteca estándar.
- **Rutas**: solo relativas, sin `..`, resueltas con `realpath` y comprobadas dentro de la carpeta de datos; los
  nombres de lectura siguen el patrón que ya exige el adaptador (`_READ_NAME`).
- **Sin datos hacia afuera**: el único tráfico nuevo es a `127.0.0.1:8080`. La instalación de Flye descarga 48 MB
  de conda.anaconda.org (paquetes, nunca datos), solo cuando el usuario lo pide con un botón.

## 3. Qué cambia

**API y modelo de trabajos** (sin migración de Alembic si se hace así):

- `parameters.execution = "docker" | "mac_native"` en el trabajo de Flye; el estado del ejecutor nativo (versión de
  la app, versión y compilación de Flye, sha256 del lock, opciones de su `--help`, último contacto) en Redis con
  vencimiento; el *lease* y el estado "esperando a la Mac" en `progress`.
- Endpoints con token: registrar/latido del ejecutor, tomar el siguiente trabajo, latido del trabajo (responde si
  hay que cancelar) y fin (código de salida, argv que corrió, ruta del ejecutable).
- `_flye_body` se separa en preparar / correr / post-procesar; en modo nativo, "correr" espera al informe de la app.
  La creación rechaza el modo nativo si la app no dio señales en el último minuto o si los datos no están en una
  carpeta del Mac.
- Procedencia: `result_summary.native` con plataforma (osx-arm64), compilación (`py313h05f0e27_1`), sha256 del lock,
  macOS y chip; `commands` guarda el argv tal como corrió (rutas de la Mac).
- La estimación de memoria (punto 29: piso fijo de ~8,5 GB) decide cuándo ofrecer el modo nativo.

**Adaptador y locks**: módulo de entrada nativo para Flye; `conda_locks.py` e `install-micromamba.sh` con
osx-arm64 opcional (sección 1); `docker/conda-locks/flye/osx-arm64.lock`; `conda_platforms` del adaptador.

**ARVA.app**: instalar/quitar "Flye para esta Mac" (micromamba fijado → entorno desde el lock → verificación);
bucle de consulta con *lease*, latido, cancelación, huérfanos y PID; textos EN/ES de la app.

**Web** (EN y ES por i18n; textos propuestos):

- en el diálogo de Flye, cuando la memoria no alcanza y el ejecutor está listo: "Run on this Mac (native)" /
  "Ejecutar en esta Mac (nativo)", con la explicación "Flye 2.9.6 reserva 8 GiB para contar k-mers, más de lo que
  Docker tiene en esta Mac. ARVA.app puede correr la misma versión de Flye directamente en macOS; el resto sigue en
  Docker.";
- estados "Waiting for ARVA.app" / "Esperando a ARVA.app" y "Running on this Mac" / "Ejecutándose en esta Mac";
- error "ARVA.app is not open" / "ARVA.app no está abierta: ábrela para que Flye pueda correr en esta Mac";
- Ajustes → Rendimiento: estado de "Flye para esta Mac" (instalado, versión, compilación).

**Pruebas**: API (token, toma exclusiva, vencimiento del *lease* → carpeta guardada para reanudar, cancelación,
fin con salidas registradas, rutas con `..` o fuera de la carpeta rechazadas, nunca se acepta argv); adaptador
(módulo nativo con un Flye falso, corre también en Linux); autoprueba de la app (`--self-test`: máquina de estados
del *lease* contra una API simulada, contención de rutas, matar un árbol de procesos falso).

**CI (`mac-app.yml`)** (escrito el 2026-11-06: trabajo `native-flye`, y en `build` el instalador propio de la app con
`--install-native-flye`): un trabajo nuevo en `macos-15` (arm64, 3 CPU M1, 7 GB de RAM según la documentación de
GitHub "GitHub-hosted runners") que instale micromamba osx-arm64 con su sha256, cree el entorno desde el lock,
corra `verify-env`, compare `flye --help` con `tests/fixtures/flye/help_2.9.6.txt`, ensamble el genoma sintético y
mida el pico de memoria (`/usr/bin/time -l`). Con 7 GB sería la primera prueba fuera de la Mac del usuario de que
el `memset` de 8 GiB pasa en macOS. Agregar a los `paths` del disparador `docker/conda-locks/flye/**` y el
adaptador.

**Estimación** (días de trabajo, sin contar las pruebas del usuario):

| Parte | Días |
|---|---|
| Locks osx-arm64 (scripts, lock, verificación) | 1 |
| API: endpoints, token, *lease*, separación de `_flye_body`, procedencia | 2,5 |
| ARVA.app: instalación de Flye, bucle, cancelación, huérfanos, textos | 3,5 |
| Web: diálogo, estados, ajustes, i18n | 1,5 |
| Pruebas (API, adaptador, autoprueba) y CI en macos-15 | 2 |
| Documentación | 0,5 |
| **Total** | **≈ 11** |

## Contrato implementado (2026-11-06)

Lo que existe hoy en el repositorio para la opción (b), para que el lado Swift se escriba contra esto. Las rutas de la
API son relativas a `http://localhost:8080/api/v1` (la misma base que usa `SleepGuard.swift`). Todo el diseño es
genérico ("ejecutor nativo" con una lista de herramientas, `app.services.native.TOOLS`); las herramientas son `flye`
y, desde el 2026-11-06, `bakta` (lo que cambia para Bakta está en **"Bakta nativo"**, al final).

### Qué está hecho y qué no

| Parte | Estado | Dónde |
|---|---|---|
| Lock osx-arm64 de Flye | hecho, generado con el mecanismo del proyecto | `docker/conda-locks/flye/osx-arm64.lock`, `native-platforms` |
| `conda_locks.py` e `install-micromamba.sh` con osx-arm64 opcional | hecho | `scripts/` |
| Entrada nativa del adaptador (mismo argv que en Docker, rutas de la Mac) | hecho, probado en Linux con un Flye falso | `arva_tools/flye.py` (sección "Native run"), `arva_tools/native.py` |
| API: token, registro, toma con *lease*, latido, fin | hecho | `app/api/routes/native.py`, `app/services/native.py` |
| Worker: Flye en preparar / correr / post-procesar, modo `mac_native` | hecho | `app/tasks/tools.py` (`_flye_prepare`, `_flye_run_docker`, `_flye_run_native`, `_flye_postprocess`) |
| Web: opción del diálogo, estados, error, Ajustes → Rendimiento | hecho, EN y ES | `FlyePanel.tsx`, `RunMonitor.tsx`, `PerformanceSection.tsx` |
| ARVA.app (instalar Flye, bucle, cancelación, huérfanos, textos) | escrito, **sin compilar** (ver "Lado de ARVA.app") | `apps/mac/ARVA/Native*.swift` |
| Trabajo de CI en `macos-15` | escrito, **sin correr** | `.github/workflows/mac-app.yml` (`native-flye` y un paso de `build`) |

El camino Docker no cambia: un trabajo sin `parameters.execution` (o con `"docker"`) hace exactamente lo de antes
(mismos enlaces absolutos, mismo argv, mismo post-proceso; las pruebas de Flye y de cancelación/reanudación siguen
pasando sin cambios).

### Lock osx-arm64

- `docker/conda-locks/flye/native-platforms` declara `osx-arm64` como plataforma **opcional** de Flye; `check` exige
  lock o `.unavailable` solo a las herramientas que la declaran.
- `python3 scripts/conda_locks.py update flye --platform osx-arm64` resuelve con `CONDA_OVERRIDE_OSX=11.0` (la línea
  `# solved with CONDA_OVERRIDE_OSX=11.0` queda en el lock). Resultado del 2026-11-06 con micromamba 2.9.0:
  19 paquetes, 48,0 MB, terminando en `bioconda/osx-arm64/flye-2.9.6-py313h05f0e27_1.conda#sha256:74a38467…b318`.
  Única diferencia con el ensayo del 2026-11-04 (sección 1): `libcxx-23.1.5-h55c6f16_0` en lugar de
  `libcxx-23.1.4-h55c6f16_2` (conda-forge publicó una compilación nueva entre las dos fechas).
- sha256 del archivo de lock: `54c2a42c2ee358b76f4776ab22bf3b7de38946f899ea2b039a8f3233fe8aa780`. Está fijado, con la
  compilación y el sha256 del paquete de Flye, en `arva_tools.flye.NATIVE_LOCK`; una prueba los compara con el archivo.
  **Si se regenera el lock hay que actualizar `NATIVE_LOCK`** (la prueba falla si no).
- `scripts/install-micromamba.sh` acepta `Darwin arm64` (`SUBDIR="osx-arm64"`, sha256
  `500f5074…3646b`, comprobado otra vez el 2026-11-06 con `conda_locks.py verify-micromamba`) y usa `shasum -a 256`
  cuando no hay `sha256sum`. En otros Mac (Intel) sale con error.
- En la Mac la secuencia que debe seguir ARVA.app: `install-micromamba.sh <prefijo temporal>`, luego `micromamba create
  --yes --no-rc --skip-run-link-scripts --prefix ~/.arva-tools/conda/flye --file osx-arm64.lock` con `MAMBA_ROOT_PREFIX`,
  `HOME` y `XDG_CACHE_HOME` en una carpeta temporal (como `conda_locks.run`), y después
  `~/.arva-tools/conda/flye/bin/python -I conda_locks.py verify-env flye ~/.arva-tools/conda/flye --platform osx-arm64`
  (macOS no trae `python3` con el que contar; el Python 3.13 del entorno sí).

### Token

- ARVA.app genera un token aleatorio (32 bytes en base64url sin `=`: 43 caracteres; se aceptan 32-256 caracteres de
  `[A-Za-z0-9_-]`) y lo escribe con permisos 0600 en `~/.config/arva/host/native-executor.token`
  (`$ARVA_CONFIG_DIR/host`, que el lanzador monta solo lectura en `/run/arva-host` cuando hay carpetas del Mac; es
  justamente el caso en que el modo nativo puede usarse). La API lo lee de `/run/arva-host/native-executor.token`
  (`ARVA_NATIVE_TOKEN_FILE`) **en cada petición**: la app puede cambiarlo al arrancar.
- Cada petición a `/native/...` lleva `Authorization: Bearer <token>`; la comparación es de tiempo constante.
  Sin archivo o con un archivo malformado: `503 native_token_missing`; sin cabecera o con otro token:
  `401 native_token_refused`. Estas rutas no usan la sesión de las cuentas (la app no tiene cuenta) y no muestran datos
  de proyectos; pasan por `LocalOrigin` (Host `localhost`) y, al ser POST, por la comprobación de la carpeta de datos.
- **A verificar en la Mac**: que el contenedor pueda leer un archivo 0600 del usuario a través del compartido de
  Docker Desktop.

Todas las peticiones son JSON y **rechazan campos desconocidos (422)**: en particular, ningún cuerpo acepta un `argv`.

### `POST /native/executor` — registro y latido del ejecutor (cada `register_seconds`, 20 s)

```json
{
  "executor_id": "6b1f3c2e-9a4d-4e8f-8c1a-2f3e4d5c6b7a",
  "app_version": "1.4.0",
  "platform": "osx-arm64",
  "macos": "15.1",
  "chip": "Apple M1",
  "memory_bytes": 8589934592,
  "data_dir": "/Volumes/JM/ARVA/data",
  "storage_id": "<el \"id\" de <data_dir>/.arva-storage>",
  "tools": { "flye": <lo que imprime `native.py flye facts`, tal cual> }
}
```

`executor_id`: un UUID que la app genera una vez y guarda. `tools.flye` = la salida de
`<entorno>/bin/python -I <bundle>/arva_tools/native.py flye facts --executable <entorno>/bin/flye --lock <lock>`:
`executable`, `version` (`flye --version`, p. ej. `2.9.6-b1802`), `package` (`version`, `build`, `sha256`, `url` del
registro `conda-meta/flye-*.json`), `lock_sha256` (del archivo de lock con que se creó el entorno), `help_options`
(las opciones de su `--help`), `samtools_helper` (flye-samtools está junto a flye) y, repetidos, `platform`, `macos`,
`chip`, `memory_bytes`.

Respuesta 200:

```json
{"executor_id": "...", "ready": {"flye": {"ready": true, "reason": null}}, "server_time": "...",
 "register_seconds": 20, "poll_seconds": 5, "heartbeat_seconds": 15, "lease_seconds": 120}
```

`reason` cuando no está lista: `platform_unsupported`, `unsafe_path` (data_dir o ejecutable no son rutas absolutas
normalizadas), `path_has_spaces` (Flye rechaza rutas con espacios: el modo nativo no se ofrece),
`storage_mismatch` (el `storage_id` no es el de la carpeta que usan los contenedores, o esa carpeta no está lista),
`other_data_dir` (el lanzador dio `ARVA_HOST_DATA_DIR` y no coincide), `lock_mismatch`, `build_mismatch`,
`version_mismatch` (no es 2.9.6), `help_incomplete`, `samtools_missing`. La API guarda el registro en Redis
(`arva:native:executor`, 7 días); el ejecutor cuenta como **abierto** si se registró en los últimos 60 s.

### `POST /native/jobs/claim` — tomar trabajo (cada `poll_seconds`, 5 s)

Cuerpo `{"executor_id": "...", "tools": ["flye"]}`. `204` si no hay trabajo. `200`:

```json
{"job_id": "...", "tool": "flye", "lease_id": "<uuid>", "lease_seconds": 120, "heartbeat_seconds": 15,
 "work": {
   "tool": "flye", "storage_id": "...", "data_dir": "/Volumes/JM/ARVA/data",
   "executable": "/Users/<u>/.arva-tools/conda/flye/bin/flye",
   "params": {"read_type": "nano-hq", "genome_size_bp": null, "iterations": 1, "threads": 2, ...},
   "reads": ["results/<proyecto>/<muestra>/<trabajo>/input/01_reads.fastq.gz"],
   "out_dir": "results/<proyecto>/<muestra>/<trabajo>/flye",
   "results_dir": "results/<proyecto>/<muestra>/<trabajo>",
   "stderr_log": "flye.stderr.log", "resume": false,
   "argv": ["/Users/<u>/.arva-tools/conda/flye/bin/flye", "--nano-hq", "/Volumes/JM/ARVA/data/results/.../input/01_reads.fastq.gz",
            "--out-dir", "/Volumes/JM/ARVA/data/results/.../flye", "--threads", "2", "--iterations", "1"],
   "timeout_seconds": 43200}}
```

- La toma es **exclusiva**: el *lease* se crea con `SET NX` en Redis (`arva:native:lease:<job>`, vence a los
  `lease_seconds`); dos tomas del mismo trabajo no pueden tener éxito las dos. Solo se ofrecen trabajos `running` del
  worker, con `execution = "mac_native"`, sin cancelación pedida y de una herramienta que este ejecutor tiene lista.
- `argv` es el que **construyó la API** (el mismo `FlyeAdapter.argv` que en Docker, con las rutas de la Mac). La app
  **no lo ejecuta tal cual**: su copia del adaptador construye el suyo con `params`, `reads`, `out_dir`, `resume`, su
  propia carpeta de datos, su ejecutable y el `--help` de su Flye, y solo corre si los dos son idénticos.
- Los enlaces a las lecturas (`input/NN_*.fastq[.gz]`) son **relativos** en el modo nativo (en Docker siguen
  absolutos), así que se resuelven igual en el contenedor y en la Mac.

### Correr: `native.py flye run`

```
<entorno>/bin/python -I <bundle>/arva_tools/native.py flye run --work work.json --data-dir <ARVA_DATA_DIR> --executable <entorno>/bin/flye
```

El bundle lleva `arva_tools/__init__.py`, `base.py`, `runner.py`, `flye.py` y `native.py` (solo biblioteca estándar;
el registro de adaptadores ya no se importa al importar `arva_tools`). Antes de correr comprueba, y si algo falla no
corre nada: que `work.data_dir` y `work.executable` sean los suyos; el `storage_id` contra `<data_dir>/.arva-storage`;
que cada ruta sea relativa con componentes `[A-Za-z0-9_][A-Za-z0-9._-]*` (nunca `.`/`..`, ni absoluta, ni `//`) y
que, resueltos los enlaces (`realpath`), quede dentro de la carpeta de datos; flye-samtools junto a flye; que el argv
propio sea idéntico al de la API. Corre como en Docker: sin shell, grupo de procesos propio, entorno limpio
(`tool_environment`: sin variables `ARVA_*` ni con TOKEN/PASSWORD/SECRET...), HOME temporal, `bin/` del entorno
primero en el PATH, `cwd` en `results_dir`, stderr a `<results_dir>/flye.stderr.log` (el worker lo lee para el
progreso). `SIGTERM` al proceso de `native.py` mata el grupo de Flye y el informe dice `"stopped"`.
`native.py flye argv ...` hace las mismas comprobaciones y solo imprime `{"argv", "cwd", "env"}`, para una app que
prefiera lanzar Flye con `Process` ella misma. Estado de salida 3 = rechazado (con el informe igual en stdout).

Informe (stdout de `run`), que la app manda tal cual:

```json
{"tool": "flye", "outcome": "exited", "exit_code": 0, "argv": [...], "executable": "...",
 "outputs": ["results/.../flye/assembly.fasta", "results/.../flye/assembly_graph.gfa", "results/.../flye/assembly_info.txt", "results/.../flye/flye.log"],
 "started_at": "...", "finished_at": "...", "duration_seconds": 812.4, "code": null, "detail": null}
```

`outcome`: `exited` (con el código de salida de Flye, negativo si fue una señal), `refused` (no se corrió nada;
`code` dice por qué: `unsafe_path`, `outside_data_dir`, `input_missing`, `storage_mismatch`, `other_data_dir`,
`other_executable`, `argv_mismatch`, `settings_rejected`, `samtools_missing`, `help_unreadable`, `path_has_spaces`,
`not_flye_work`, `work_incomplete`), `stopped` (SIGTERM de la app, o el límite de tiempo) o `not_started`.

### `POST /native/jobs/{job_id}/heartbeat` — latido del trabajo (cada `heartbeat_seconds`, 15 s)

Cuerpo `{"executor_id": "...", "lease_id": "...", "pid": 12345}` (`pid` opcional: el de `native.py`, para que la
app lo guarde y mate huérfanos al volver a abrirse). Respuesta `{"cancel": false, "lease_seconds": 120,
"heartbeat_seconds": 15}`. `cancel: true` cuando el usuario canceló, cuando pasó el límite de tiempo
(`ARVA_TOOL_TIMEOUT_SECONDS`) o cuando el trabajo ya no está corriendo en ARVA: la app manda SIGTERM a `native.py`
(o mata el árbol de Flye) y termina con `outcome: "stopped"`. `409 native_lease_lost`: el *lease* venció o no es de
este ejecutor; la app debe **matar Flye** y no mandar nada más.

### `POST /native/jobs/{job_id}/finish` — fin

Cuerpo `{"executor_id": "...", "lease_id": "...", "report": <informe de run>}`. `200 {"accepted": true}`. Se acepta
una sola vez (`409 native_already_finished`). **`422` y el trabajo falla** si el `argv` de un informe `exited` o
`stopped` no es exactamente el que construyó la API (`native_argv_mismatch`), si `executable` es otro
(`native_executable_mismatch`) o si una ruta de `outputs` no es una de las cuatro salidas de Flye dentro del `out_dir`
del trabajo, tenga `..`, sea absoluta o salga de la carpeta (`native_unsafe_path`).

### Reglas del *lease* y estados del trabajo

- El worker sigue siendo dueño del trabajo (`status = running` todo el tiempo, así que `SleepGuard` mantiene la Mac
  despierta). `job.progress.native.state` = `waiting_for_app` hasta la toma y `running_on_mac` después (con
  `app_open`, versión de la app, macOS y chip); el resto de `progress` (etapas, log) es el de siempre.
- Sin latido durante `lease_seconds` (120 s) el *lease* vence: el trabajo falla con `native_lease_expired` y, si Flye
  había completado una etapa después de `configure`, **se guarda su carpeta de trabajo para reanudar**
  (`checkpoint.reason = "native_stopped"`, `execution = "mac_native"`, `build`). Un `stopped` sin cancelación ni límite
  de tiempo (la app se cerró) hace lo mismo con `native_stopped`.
- Reanudar un trabajo nativo crea otro trabajo nativo y exige la misma versión **y la misma compilación** de Flye
  (nativo con nativo); un trabajo Docker se sigue reanudando en Docker.
- Un trabajo esperando sin que ninguna app se registre durante 15 min falla con `native_app_not_open`. Cancelar antes
  de la toma termina el trabajo sin la app. Cancelar después espera el informe `stopped` (como mucho 120 s).
- La creación (`POST /samples/{id}/assembly/flye` con `"execution": "mac_native"`) responde `409
  native_app_not_open` si la app no se registró en el último minuto, `409 native_not_ready` (con `reason`) si no puede
  correr Flye y `409 native_tool_not_installed` si no registró Flye. El trabajo guarda el Flye de la Mac como
  herramienta (`tool_path`, `tool_version`) y valida las opciones contra el `--help` que la app registró.

### Procedencia

- `parameters.execution = "mac_native"` y `parameters.native_executor` (lo que la app registró al encolar).
- `commands` = el argv tal como corrió (rutas de la Mac), `tool_path` = el ejecutable de la Mac.
- `result_summary.execution = "mac_native"` y `result_summary.native`: `platform` (osx-arm64), `build`
  (`py313h05f0e27_1`), `package_sha256`, `lock`, `lock_sha256`, `flye_version`, `executable`, `app_version`,
  `executor_id`, `macos`, `chip`, `memory_bytes`, `data_dir`, `argv`, `exit_code`, `started_at`, `finished_at`,
  `duration_seconds`, `reported_outputs`. El registro del trabajo dice en una línea dónde y con qué compilación corrió.

### Cuándo se ofrece en la web

- El diálogo de Flye muestra "Run on this Mac (native)" / "Ejecutar en esta Mac (nativo)" cuando la estimación de
  memoria de la vista previa da `below_floor`, `tight` o `may_not_fit` (punto 29: el piso fijo de ~8,6 GB de la tabla
  de k-mers) **y** ARVA.app registró un Flye (`plan.native.offered`). Si la app está abierta y lista, se puede elegir;
  si no, se muestra "ARVA.app no está abierta: ábrela para que Flye pueda correr en esta Mac" (u otra razón) y el
  botón queda bloqueado mientras esté marcada. En Linux, o sin ARVA.app, no aparece nada.
- El trabajo en curso muestra "Esperando a ARVA.app" o "Ejecutándose en esta Mac"; Ajustes → Rendimiento muestra
  "Flye para esta Mac": app abierta o no (último contacto), macOS y chip, versión y compilación instaladas, si salió
  del lock de ARVA y si está lista. Ruta de la API: `GET /system/native-executor`.

### Lo que le queda a ARVA.app (Swift)

Instalar/quitar "Flye para esta Mac" (micromamba fijado → entorno desde el lock → `verify-env`), escribir el token,
registrarse cada 20 s mientras está abierta, tomar trabajos cada 5 s, correr `native.py flye run` con `Process`
(argv en lista, sin shell), latir cada 15 s, matar en `cancel`/`409`, mandar el informe, guardar el PID en la
carpeta del trabajo y matar un Flye huérfano al volver a abrirse, matar Flye al cerrarse, y sus textos EN/ES. Hecho
(sin compilar) el 2026-11-06: ver la sección siguiente.

## Lado de ARVA.app (2026-11-06, escrito sin compilar)

Archivos: `apps/mac/ARVA/NativeFlye.swift` (rutas, comprobaciones de rutas, token, instalación),
`NativeExecutor.swift` (máquina de estados del *lease*, cliente de la API, proceso de `native.py`, huérfanos, el
ejecutor), `NativeFlyeUI.swift` (menú **ARVA → Flye para esta Mac…**), `NativeSelfTest.swift` (parte de
`--self-test`); cambios en `AppDelegate.swift`, `MainMenu.swift`, `SelfTest.swift`, `main.swift` y
`scripts/build-mac-app.sh` (paso 3b: copia en `Contents/Resources/native` `arva_tools/{__init__,base,runner,flye,
native}.py`, `scripts/conda_locks.py`, `scripts/install-micromamba.sh`, el lock osx-arm64, `native-platforms` y
`help_2.9.6.txt`).

- **Instalar**: comprueba Apple silicon (la porción arm64 de la app, no Rosetta) y que la ruta del entorno no tenga
  espacios; ejecuta el `install-micromamba.sh` del bundle (sha256 fijado) en una carpeta temporal dentro de
  `~/.arva-tools`; `micromamba create --yes --no-rc --skip-run-link-scripts --prefix ~/.arva-tools/conda/flye --file
  <lock del bundle>` con `MAMBA_ROOT_PREFIX`, `HOME` y `XDG_CACHE_HOME` temporales y un entorno mínimo (PATH del
  sistema, proxies si los hay, nada de `ARVA_*`, `CONDA*`, `MAMBA*`); `python -I -B conda_locks.py verify-env flye
  … --platform osx-arm64`; copia el lock a `<entorno>/arva-native/osx-arm64.lock`; `native.py flye facts` y compara
  versión 2.9.6, compilación y sha256 del paquete (leídos de la última línea del lock), sha256 del lock (`shasum`),
  `flye-samtools` y las opciones de `--help` contra `help_2.9.6.txt` (mismo patrón que `_FLAG`). Si todo está bien
  escribe `<entorno>/arva-native/install.json`; si no, borra el entorno a medio hacer. `-B` evita escribir
  `__pycache__` dentro de la app firmada. Los registros quedan en `~/Library/Application Support/ARVA/logs/native/`.
  `ARVA --install-native-flye` / `--remove-native-flye` hacen lo mismo sin ventana (lo usa el CI).
- **Quitar**: borra `~/.arva-tools/conda/flye` solo si tiene el `install.json` de ARVA.app.
- **Token**: 32 bytes de `SystemRandomNumberGenerator` en base64url (43 caracteres), creado con `open(O_CREAT|O_EXCL,
  0600)` y renombrado sobre `$ARVA_CONFIG_DIR/host/native-executor.token`; uno nuevo cada vez que arranca el ejecutor.
- **Bucle** (temporizador de 1 s en el hilo principal): arranca cuando ARVA responde y Flye está instalado, y después
  de buscar huérfanos. Registro cada `register_seconds` con lo que imprime `native.py flye facts` (leído al arrancar y
  después de instalar), `data_dir` = `ARVA_DATA_DIR` de `arva.conf` y el `id` de `.arva-storage`; sin carpeta de la
  Mac no se registra. Toma cada `poll_seconds` solo si la API dijo `ready`. Latido cada `heartbeat_seconds` con el
  PID de `native.py`.
- **Máquina de estados del *lease*** (`NativeLease`, sin efectos: devuelve acciones): `idle → launching → running →
  [stopping] → finishing → idle`. `cancel: true` → SIGTERM a `native.py` y se manda su informe `stopped`. `409
  native_lease_lost`, o ningún latido exitoso durante `lease_seconds` → se mata Flye y no se manda nada más. El
  informe se manda una vez; si no llega, se reintenta (5 intentos en total) mientras el *lease* pueda seguir vivo;
  `409`/`422` son respuestas finales.
- **Correr**: antes de escribir nada, la app repite las comprobaciones de `native.py` sobre el registro de trabajo
  (herramienta, carpeta de datos, ejecutable, nombre del log, rutas relativas con los mismos componentes que
  `_REL_PART`, `realpath` dentro de la carpeta de datos, `out_dir` dentro de `results_dir`); si algo falla manda un
  informe `refused` sin correr nada. Si no, escribe el registro (0600) en `~/Library/Application Support/ARVA/native/`
  y lanza `<entorno>/bin/python -I -B <bundle>/arva_tools/native.py flye run --work … --data-dir … --executable …`
  con `Process` (argv en lista, sin shell), entorno mínimo, stdout = el informe, stderr a
  `logs/native/run-<trabajo>.log`. El log de Flye lo escribe `native.py` en `<results>/flye.stderr.log`, donde lo
  lee el worker. `detail` se acorta a 2000 caracteres (el límite de la API); el resto del informe va tal cual.
- **Cancelar / matar**: SIGTERM a `native.py` (mata el grupo de Flye e imprime `stopped`); si a los 30 s sigue vivo,
  `ProcessTree.terminate` sobre todo el árbol (SIGSTOP, SIGTERM, SIGKILL); después se matan los descendientes
  anotados que sigan con la misma línea de comando.
- **PID y huérfanos**: el árbol de `native.py` (PID y línea de comando, `ps -A -ww`) se guarda en
  `~/Library/Application Support/ARVA/native/running.json` al lanzar y en cada latido. Al abrirse la app, antes de
  arrancar el ejecutor, mata los procesos anotados que **siguen con la misma línea de comando** y la tienen de
  `native.py` o del entorno de Flye (nunca otro programa que haya recibido el mismo PID); el *lease* vence solo y el
  worker guarda la carpeta para reanudar.
- **Salir**: "Salir sin detener" y "Detener y salir" detienen primero Flye y esperan su informe (hasta 45 s) mientras
  la API todavía responde; `applicationWillTerminate` lo hace de forma síncrona por si acaso. El aviso «¿Detener
  ARVA?» dice que Flye se detendrá. Mientras corre, el menú ARVA muestra «Flye se está ejecutando en esta Mac
  (nativo)».
- **Autoprueba** (`--self-test`, en el CI): archivos del bundle, lock y `--help`; la máquina de estados contra una API
  simulada con las reglas de `app/services/native.py` (toma exclusiva, latidos, cancelación, *lease* perdido, API
  caída 120 s, salir, no arrancó, argv distinto rechazado, reintento y abandono del informe); rutas (`..`, absolutas,
  enlaces que salen de la carpeta, carpeta de Flye bajo un enlace que sale); registro de trabajo; token (0600,
  reemplazo); informe; peticiones; matar un árbol falso que responde a SIGTERM y otro que lo ignora (con nietos en su
  propio grupo); huérfanos (se mata el anotado, no uno con otra línea de comando).

**Diferencias con lo escrito antes en este plan**:

- El entorno está en `~/.arva-tools/conda/flye`, no en la carpeta de soporte de la app
  (`~/Library/Application Support` tiene un espacio, que `native_executable` y Flye rechazan).
- El PID se guarda en la carpeta de soporte de la app (`native/running.json`), no en la carpeta del trabajo, para no
  dejar archivos ajenos entre los resultados ni depender de que el disco de datos esté conectado al reabrir.
- La app nunca ejecuta el argv de la API: ejecuta `native.py`, que arma el suyo y corre solo si es idéntico.

**Lo que falta o solo se sabe en la Mac / en el CI**: que compile (Swift 5, macOS 13; no hay compilador de Swift en
el entorno donde se escribió); que micromamba osx-arm64 descargue con el entorno mínimo (sin `SSL_CERT_FILE`); que
la API lea el token 0600 a través del compartido de Docker Desktop; la carga real de Flye nativo con Docker abierto
en una Mac de 8 GB (el CI mide el pico en `macos-15`, 7 GB, sin Docker).

## 4. Riesgos y lo que solo se puede verificar en la Mac del usuario

1. **Memoria con Docker abierto**: ¿estaba Docker Desktop corriendo cuando el usuario corrió Flye nativo? La VM de
   Docker (6 GB configurados) y Flye juntos en 8 GB pueden llevar la Mac a usar swap en disco. Hay que medirlo con
   ARVA abierto (Monitor de Actividad, `memory_pressure`) y quizá recomendar bajar la memoria de Docker mientras
   tanto.
2. **Que la compilación osx-arm64 se comporte como la de Linux**: `flye --version`, el `--help` (que el adaptador
   compara) y el resultado sobre el genoma sintético; y, en privado, sobre la cepa del usuario contra su propio
   ensamblaje. Es otra compilación: el registro lo debe decir siempre.
3. **Firma y cuarentena** de los binarios instalados por micromamba (en Apple silicon todo código debe estar
   firmado, aunque sea ad hoc): comprobar que Flye arranca sin "Killed: 9" ni avisos de Gatekeeper.
4. **Permiso de macOS para el disco externo**: la primera vez que ARVA.app (y no Docker) lea `/Volumes/JM` puede
   aparecer el aviso de acceso a volúmenes extraíbles.
5. **Archivos compartidos**: que la VM vea a tiempo el log que escribe Flye en la Mac (para el progreso) y que los
   enlaces relativos funcionen en el sistema de archivos del disco.
6. **Solo (a)**: si `host.docker.internal` alcanza un servicio que escucha solo en 127.0.0.1.
7. **Ruta con espacios**: con datos en una carpeta con espacios el modo nativo no puede ofrecerse.
8. **Mac dormida por tapa cerrada**: como hoy, la aserción no lo impide (IOPMLib.h).

## Alternativas sin este desarrollo

- **Seguir fuera de ARVA** (la otra opción del punto 32): ensamblar con Flye en la Terminal y usar "Registrar un
  FASTA de genoma"; para pulirlo en ARVA falta el punto 33.
- **Probar antes más swap para Docker** (sin código): con 6 GB + 2 GB de swap falló (punto 29) con un pico de
  8,8 GB; con más swap podría entrar, a costa de escribir ceros a disco. El máximo del ajuste "Swap" no figura en
  la documentación de Docker Desktop ("1 GB default"): verlo en la Mac. No soluciona el caso general, pero cuesta
  una prueba.

## Bakta nativo (2026-11-06)

Punto 49 del registro: Bakta 1.12.2 con la base completa 6.0 falló en Docker (5,9 GB) porque el sistema mató a
DIAMOND. Bakta fija `--block-size 3` (`bakta/psc.py`, `pscc.py`, `features/s_orf.py`) y no tiene opción para cambiarlo.
El Bakta 1.11.4 del propio usuario corrió con esa base de forma nativa en la misma Mac (punto 51). Se resolvió con el
mismo ejecutor nativo de Flye y, además, con una estimación de memoria antes de lanzar.

### Factibilidad (comprobada, no supuesta)

- `python3 scripts/conda_locks.py update bakta --platform osx-arm64` (micromamba 2.9.0, `CONDA_OVERRIDE_OSX=11.0`)
  produjo `docker/conda-locks/bakta/osx-arm64.lock`: **140 paquetes, 296,2 MB**. sha256 del archivo
  `8a302d44802fc18019bef6e81d46adc4228c8bcf66d1a40605f0e6978b21205b` (fijado en `arva_tools.bakta.NATIVE_LOCK`;
  una prueba lo compara). `docker/conda-locks/bakta/native-platforms` declara `osx-arm64` como plataforma opcional.
- Bakta es `noarch` (`bakta-1.12.2-pyhdfd78af_0.conda`, sha256 `8bc71bb2…615d`, el mismo archivo que el lock de Linux).
  Todos los programas que Bakta comprueba al arrancar están en el lock para osx-arm64: diamond 2.2.8, blast 2.17.0,
  ncbi-amrfinderplus 4.2.7, trnascan-se 2.0.13, infernal 1.1.5, aragorn 1.2.41, piler-cr 1.06, pyrodigal 3.7.1
  (otra compilación que en Linux: `py313h966660b_1`), pyhmmer 0.12.3 y hmmer 3.4; pycirclize y el resto de
  conda-forge en `osx-arm64` o `noarch`.

### Estimación de memoria (también para Docker)

`arva_tools.bakta.memory_estimate`: DIAMOND procesa la referencia en bloques de hasta 3.000 millones de letras
("Block size in billions of sequence letters to be processed at a time", wiki de DIAMOND, "3. Command line
options"); Bakta corre sus búsquedas una tras otra, así que decide el bloque más grande. Las letras de cada `.dmnd`
se leen de su cabecera (número mágico, build, versión, secuencias, letras; comprobado contra lo que DIAMOND 2.2.8
imprime para la base light 6.0: 3.557.503 secuencias, 1.245.018.838 letras).

- **Bytes por letra: medidos por ARVA** (no documentados): DIAMOND 2.2.8 linux-64 con los argumentos exactos de
  `pscc.py` sobre `pscc.dmnd` de la base light 6.0 y las 2.646 proteínas de *S. aureus* N315 (GCF_000011265.1):
  pico de memoria residente 2.933.644 KiB con 2 hilos y 2.932.388 KiB con 4 (mismos aciertos) → **2,41 bytes por
  letra**, sin depender de los hilos. La cifra de la documentación de DIAMOND ("roughly six times this number of
  memory (in GB)") es una cota más gruesa que ARVA no usa: diría que la light no entra en 5,9 GB, y entró (punto 53).
- Resultado: light 6.0 → **2,8 GB** (entra en 5,9 GB: coincide con el punto 53); un bloque completo de 3.000
  millones de letras (la `psc.dmnd` de la base completa; su tamaño exacto no se leyó aquí, solo en la Mac) → **6,7
  GB** (no entra en 5,9 GB: coincide con el punto 49). GB de 1024³ bytes, como la memoria del contenedor que muestra
  ARVA. Veredictos: `fits` (con 1 GB de margen para el proceso de Bakta y el resto, margen supuesto, no medido),
  `tight`, `may_not_fit`, `unknown`.
- El diálogo de Bakta (vista previa: `plan.memory`) avisa cuando no entra o queda justo y ofrece **"Usar la base
  light"** si hay una registrada (con su propia estimación). El trabajo guarda la estimación que se vio
  (`parameters.memory_estimate`).

### Qué cambia respecto del contrato de Flye

- **Registro** (`POST /native/executor`): `tools.bakta` = lo que imprime `native.py bakta facts` (versión `bakta
  1.12.2`, paquete, sha256 del lock, opciones del `--help`, y `dependencies`: los chequeos de arranque de Bakta con los
  programas del entorno de la Mac, sin base). Campo nuevo `database_dirs`: las carpetas de bases de `arva.conf`
  (`ARVA_DATABASES_DIR` y cada `ARVA_ADD_DATABASES`), con los enlaces resueltos. Razones nuevas: `no_database_folders`
  y `tool_mismatch` (los datos de una herramienta enviados con el nombre de otra).
- **Bases de datos**: viajan como `{"root": <carpeta de la Mac>, "rel": <ruta dentro>}`. La API toma `root` del
  `host_path` de la ubicación de ARVA que contiene la base (el lanzador lo da para `/databases` y
  `/databases-external/<n>`) y exige que esté en `database_dirs`. Con la base en un volumen de Docker:
  `native_database_not_on_mac`; con una carpeta que la app no informó: `native_database_folder_unknown`; con una ruta
  que no es simple: `native_database_unusable`. `native.py` solo acepta raíces dadas con `--database-dir` (las de
  `arva.conf`) y comprueba con `realpath` que la ruta quede dentro (`outside_database_dir`).
- **Vista previa** (`POST /assemblies/{id}/annotate/bakta/preview` con `"execution": "mac_native"`): los programas y
  los pasos son los que ARVA.app encontró en la Mac, con la comprobación de la base de AMRFinderPlus hecha en Docker
  con la misma versión (4.2.7). `plan.native`: `offered` (la memoria no alcanza y la app registró un Bakta), `ready`,
  `reason`, la base como la ve la Mac.
- **Trabajo de Bakta** (`execution: "mac_native"`): `_bakta_body` se separó en preparar / correr (Docker o Mac) /
  post-procesar. El registro de trabajo trae `genome`, `out_dir`, `tmp_dir`, `results_dir`, `console_log`
  (`bakta.console.log`), `database`, `amr_data`, `database_type`, `skip_options` (las confirmadas) y el `argv` que
  construyó la API.
- **En la Mac** (`native.py bakta run … --database-dir D …`): antes de correr nada repite los chequeos de arranque de
  Bakta con los programas del entorno y **rechaza con `programs_changed`** si los pasos que se pueden correr no son
  los confirmados; arma el argv con el mismo `BaktaAdapter.argv` y corre solo si es idéntico. Cuando los datos de
  AMRFinderPlus reemplazan la copia de la base (AMRFinderPlus 4.2.7 rechaza la 2024-12-18.1 de las bases 6.0), la
  vista `bakta-tmp/database` se arma **en la Mac**, con las rutas de la Mac, recién después de todas las
  comprobaciones (los enlaces absolutos del contenedor no apuntarían a nada en macOS). El informe trae también
  `dependencies` (lo que se encontró en la Mac); la API solo acepta salidas `annotation.*` dentro del `out_dir`.
- **Fallos**: códigos propios para que la interfaz nombre a Bakta (`bakta_native_refused`,
  `bakta_native_lease_expired`, `bakta_native_app_not_open`, `bakta_native_stopped`) y
  `bakta_out_of_memory_native` (macOS mató a DIAMOND aunque corrió nativo: cerrar otras aplicaciones —la VM de Docker
  conserva su memoria— o usar la base light). Bakta no tiene punto de control: una ejecución detenida se vuelve a
  lanzar desde el principio.
- **Procedencia**: `result_summary.execution = "mac_native"` y `result_summary.native` (plataforma, compilación,
  sha256 del paquete y del lock, `bakta_version`, ejecutable, app, macOS, chip, memoria, argv, base y datos de
  AMRFinderPlus como raíz + ruta); los programas (`programs`) son los de la Mac (`on_mac`).
- **Web**: en el diálogo de Bakta, el aviso de memoria con "Usar la base light" y la opción "Ejecutar en esta Mac
  (nativo)" cuando se ofrece; el trabajo en curso muestra "Esperando a ARVA.app" / "Ejecutándose en esta Mac" con el
  nombre de Bakta; Ajustes → Rendimiento muestra "Bakta para esta Mac".
- **ARVA.app** (escrito, **sin compilar**): `NativeTool` (Flye y Bakta: entorno en `~/.arva-tools/conda/<tool>`,
  lock, `--help`), menú **ARVA → Bakta para esta Mac…** (instalar / reinstalar / quitar, unos 296 MB), `ARVA
  --install-native-bakta` / `--remove-native-bakta`, registro de las dos herramientas y de `database_dirs`, toma de
  trabajos de las herramientas listas, comprobación previa del registro de trabajo de Bakta (`NativeWorkCheck`) y
  `native.py bakta run` con un `--database-dir` por carpeta. El paquete de la app lleva además
  `arva_tools/{native_common,bakta,nanoplot,amrfinderplus}.py`, el lock y `native-platforms` de Bakta y
  `fixtures/bakta/help_1.12.2.txt`.
- **CI** (`mac-app.yml`, escrito, sin correr): en `build`, el instalador de la app con `--install-native-bakta`,
  `verify-env`, `bakta --version`, `native.py bakta facts` con los 10 chequeos de arranque en `ok`, y quitarlo.

### Lo que falta o solo se sabe en la Mac

- Que compile el lado Swift y que el instalador cree el entorno de Bakta en `macos-15`.
- **No se corrió ninguna anotación nativa** (ni en el CI: haría falta bajar la base light, 1,4 GB, y una base de
  AMRFinderPlus). La primera será en la Mac del usuario.
- El pico real de DIAMOND 2.2.8 con la base completa en macOS nativo (y si con Docker abierto entra en 8 GB sin
  usar mucho swap); el tamaño real de la `psc.dmnd` de la base completa 6.0 (la estimación la lee en la Mac).
- Que las rutas de `arva.conf` (con enlaces resueltos) coincidan con las que el lanzador pasa a los contenedores:
  si no, la vista previa dice `native_database_folder_unknown`.
- Bakta con rutas con espacios no se probó: ARVA no ofrece el modo nativo con espacios en las rutas (como Flye).
