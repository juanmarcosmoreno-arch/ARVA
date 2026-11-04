# Plan: Flye nativo en macOS desde ARVA.app

Punto 32 del registro de la prueba en la Mac (`docs/registro-prueba-mac.md`). **Solo diseño, para decidir**: no hay
código de producto todavía. Fecha de las comprobaciones: 2026-11-04.

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

**CI (`mac-app.yml`)**: un trabajo nuevo en `macos-15` (arm64, 3 CPU M1, 7 GB de RAM según la documentación de
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
