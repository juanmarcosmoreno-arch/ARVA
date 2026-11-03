# ARVA.app: ARVA como una aplicación de la Mac

ARVA.app es la forma más sencilla de usar ARVA en una Mac: se abre con doble clic como cualquier otra aplicación,
inicia ARVA (abre Docker Desktop si hace falta) y lo muestra en su propia ventana. Al salir pregunta si detener
ARVA para liberar memoria. No hace falta usar la terminal ni un navegador.

Sirve igual para pasarle ARVA a otra persona: le basta con instalar **Docker Desktop**; la aplicación hace el resto,
incluidas las preguntas del primer inicio.

> **Estado.** La aplicación se compila y se prueba automáticamente en una Mac de GitHub (con su autoprueba), pero
> **todavía no se probó en uso real** con Docker Desktop. Si algo no coincide con esta guía, ver
> [Qué hacer cuando algo falla](#qué-hacer-cuando-algo-falla).

## Contenido

1. [Qué se necesita](#qué-se-necesita)
2. [Conseguir ARVA.app](#conseguir-arvaapp)
3. [Moverla a Aplicaciones](#moverla-a-aplicaciones)
4. [La primera vez que se abre](#la-primera-vez-que-se-abre)
5. [El primer inicio de ARVA](#el-primer-inicio-de-arva)
6. [El uso diario](#el-uso-diario)
7. [Salir: qué hace el aviso «¿Detener ARVA?»](#salir-qué-hace-el-aviso-detener-arva)
8. [Pasarle ARVA a otra persona](#pasarle-arva-a-otra-persona)
9. [Si ya se usaba ARVA desde la carpeta ARVA o con ARVA.command](#si-ya-se-usaba-arva-desde-la-carpeta-arva-o-con-arvacommand)
10. [Qué hacer cuando algo falla](#qué-hacer-cuando-algo-falla)
11. [Para quien la compila](#para-quien-la-compila)

## Qué se necesita

| Qué | Detalle |
|---|---|
| Mac | Con chip de Apple (M1, M2, M3…) o con procesador Intel: la aplicación funciona en las dos. |
| macOS | 13 (Ventura) o posterior, y una versión que Docker Desktop admita. |
| Docker Desktop | Gratuito para uso personal, educativo y en organizaciones pequeñas. Si falta, ARVA.app lo dice y abre la página de descarga. |
| Internet | La primera vez, para descargar los programas de ARVA (varios GB). Después solo para actualizaciones y bases de datos. Los análisis corren en la Mac: ARVA no envía lecturas, genomas ni resultados a ningún lado. |
| Disco externo (opcional) | Si los datos van a un disco externo, formateado como **APFS** o Mac OS Plus (no exFAT ni FAT). Ver [guia-mac.md](guia-mac.md), paso 1. |

## Conseguir ARVA.app

Hay dos formas:

**A. Descargarla ya hecha (lo más fácil).**

1. Abrir la página de **Actions** del repositorio de ARVA en GitHub y elegir el flujo **Mac app**
   (<https://github.com/juanmarcosmoreno-arch/ARVA/actions/workflows/mac-app.yml>). Hace falta haber iniciado sesión
   en GitHub.
2. Abrir la ejecución más reciente que tenga una marca verde ✓.
3. Abajo, en **Artifacts**, hacer clic en **ARVA-mac.zip**. Se descarga a la carpeta Descargas.
4. Hacer doble clic en `ARVA-mac.zip` (si Safari no lo descomprimió solo): aparece **ARVA** (ARVA.app).

Cada ejecución guarda su archivo 30 días; después hay que tomar uno más reciente.

**B. Compilarla en la propia Mac.** Hace falta Xcode o las herramientas de línea de comandos de Apple
(se instalan con `xcode-select --install` en Terminal). En la carpeta del código de ARVA:

```sh
scripts/build-mac-app.sh
```

Al terminar, la aplicación está en `apps/mac/build/ARVA.app` y el archivo para compartir en
`apps/mac/build/ARVA-mac.zip`. No se descarga nada de internet para compilarla.

## Moverla a Aplicaciones

Arrastrar **ARVA** a la carpeta **Aplicaciones** (en Finder, barra lateral → Aplicaciones). Conviene hacerlo antes de
abrirla la primera vez: macOS trata distinto a las aplicaciones que se abren desde Descargas. Para tenerla a mano,
arrastrarla después desde Aplicaciones al Dock.

## La primera vez que se abre

ARVA.app no está firmada por un desarrollador registrado en Apple (no pasó por la «notarización» de Apple), así que
la primera vez macOS la bloquea con un mensaje como «No se puede abrir "ARVA" porque Apple no puede comprobar si
contiene software malicioso». Es esperable. Para abrirla **una sola vez** de forma permitida:

- **macOS 15 (Sequoia) o posterior:** hacer doble clic en ARVA y cerrar el aviso (botón **Listo** u **OK**). Después
  abrir **Ajustes del Sistema → Privacidad y seguridad**, bajar hasta **Seguridad**: aparece «Se bloqueó el uso de
  "ARVA"…». Pulsar **Abrir igualmente**, confirmar con la contraseña de la Mac (o Touch ID) y pulsar **Abrir**.
- **macOS 13 o 14:** en Aplicaciones, hacer **Control-clic** (o clic derecho) en ARVA → **Abrir**, y en el aviso
  pulsar **Abrir**. (Si no aparece el botón, usar el camino de Ajustes del Sistema de arriba.)

Desde entonces se abre con doble clic, como cualquier aplicación. Al reemplazarla por una versión nueva puede pedirlo
otra vez.

macOS también puede preguntar, la primera vez, si ARVA puede acceder a la carpeta **Descargas** (para guardar los
informes que se descargan) o a un **disco externo** (donde están los datos). Hay que pulsar **Permitir**. Si por error
se pulsó **No permitir**, ARVA no llega al disco aunque esté conectado: se arregla en **Ajustes del Sistema →
Privacidad y seguridad → Archivos y carpetas → ARVA**, activando **Volúmenes extraíbles** (y lo mismo para
**Terminal** si el aviso salió durante las preguntas del primer inicio).

## El primer inicio de ARVA

Al abrir ARVA.app se ve una ventana pequeña con el logo de ARVA y lo que está pasando:

1. **Docker Desktop.** Si no está instalado, aparece «ARVA necesita Docker Desktop» con el botón **Descargar Docker
   Desktop**: descargarlo (elegir *Mac with Apple chip* o *Mac with Intel chip*), instalarlo, abrirlo y aceptar sus
   condiciones. ARVA.app sigue sola en cuanto Docker está listo. Si está instalado pero cerrado, ARVA.app lo abre y
   muestra «Abriendo Docker…» hasta que responde (la primera vez puede tardar un par de minutos).
2. **Las preguntas del primer inicio.** Cuando en esa Mac nunca se configuró ARVA, aparece «Te damos la bienvenida a
   ARVA». Al pulsar **Continuar** se abre una ventana de **Terminal** con unas preguntas, sobre todo en qué disco
   guardar los proyectos y las bases de datos (por ejemplo `/Volumes/<disco>/ARVA`). Se contestan escribiendo y
   pulsando Enter; las preguntas explican cada opción. Son las mismas que se describen en
   [guia-mac.md](guia-mac.md), paso 6.
   La última pregunta es «¿Guardar estas elecciones e iniciar ARVA?»: si se contesta que no, no se guarda nada y
   ARVA.app ofrece **Responder de nuevo**.
3. **La descarga.** Después ARVA descarga sus programas (varios GB, puede tardar un rato según la conexión).
   La ventana de Terminal lo va mostrando, y ARVA.app también, en **Detalles**.
4. **ARVA se abre solo** en la ventana de ARVA.app cuando está listo (no hace falta el navegador: no se abre).
   La ventana de Terminal ya se puede cerrar.

Mientras se contestan las preguntas no hay que cerrar la ventana de Terminal: si se cierra (o se pulsa Control-C),
ARVA.app lo nota y ofrece **Reintentar** para empezar de nuevo. **Cancelar** en la ventana de ARVA.app también detiene
las preguntas de Terminal.

Las respuestas quedan guardadas: las veces siguientes no se pregunta nada. Para cambiarlas más adelante (por
ejemplo, otro disco), menú **ARVA → Volver a configurar…**.

## El uso diario

- **Abrir:** doble clic en ARVA (o clic en el Dock). Si Docker Desktop está cerrado, se abre solo. Si ARVA ya estaba
  en marcha, aparece enseguida; si no, se ve «Iniciando ARVA…» unos segundos (o unos minutos cuando hay una versión
  nueva que descargar). El triángulo **Detalles** muestra lo que va haciendo, por si alguien lo pide.
- **Trabajar:** todo ARVA funciona dentro de la ventana, igual que en el navegador:
  - **Subir archivos:** arrastrar los FASTQ a la zona de carga, o hacer clic en ella para elegirlos (se pueden
    elegir varios a la vez).
  - **Descargar** informes y exportaciones: se guardan en **Descargas**; abajo aparece un aviso con el botón
    **Mostrar en Finder**. Si ya existe un archivo con ese nombre, el nuevo se llama, por ejemplo, `informe (2).html`.
  - **Enlaces externos** (NCBI, documentación, citas): se abren en el navegador de siempre.
  - Para corridas muy grandes, en vez de subir: menú **Archivo → Abrir la carpeta de importación**, copiar allí los
    archivos y en ARVA usar **Importar datos → Importar desde una carpeta del servidor**. Ese menú abre siempre la
    carpeta que ARVA está leyendo: la que se eligió en las preguntas del primer inicio, o si no se eligió ninguna,
    `~/Library/Application Support/ARVA/runtime/import`. Si la carpeta elegida está en un disco que no está conectado,
    lo avisa.
- **Menús útiles:** **Visualización → Volver a cargar la página** (⌘R), **Ampliar / Reducir / Tamaño real**
  (⌘+, ⌘−, ⌘0), **Ver en el navegador** (⇧⌘B: abre la misma página en Safari u otro navegador), **Pantalla completa**.
  **Edición** tiene Copiar, Pegar y Seleccionar todo como siempre.
- La ventana recuerda su tamaño y posición.
- **Disco externo:** si los datos están en un disco externo, conectarlo **antes** de abrir ARVA.app.

## Salir: qué hace el aviso «¿Detener ARVA?»

Al salir (⌘Q, menú ARVA → Salir de ARVA, o cerrando la ventana) aparece **«¿Detener ARVA?»** con tres botones:

| Botón | Qué hace |
|---|---|
| **Detener y salir** (el resaltado; también con Enter, salvo si hay análisis en curso) | Detiene ARVA (sus contenedores de Docker) para liberar la memoria que usa, y cierra la aplicación. Los proyectos, las bases de datos y los resultados **se conservan**; la próxima vez ARVA se inicia de nuevo. |
| **Salir sin detener** | Cierra solo la ventana: ARVA sigue funcionando por detrás (por ejemplo, para que termine un análisis largo). Si ARVA todavía se estaba iniciando, el inicio sigue hasta terminar. Se puede volver a abrir ARVA.app, o entrar en <http://localhost:8080> con el navegador. |
| **Cancelar** (o Esc) | No sale. |

- Si hay **análisis en curso o en espera**, el aviso lo dice: detener ARVA los interrumpe (se pueden volver a
  lanzar después). Para que terminen, elegir **Salir sin detener**; en ese caso es el botón resaltado (Enter), para
  no interrumpirlos sin querer.
- Si se sale mientras ARVA todavía se está iniciando y se elige **Detener y salir**, primero se corta el inicio y
  después se detiene ARVA.
- Si fue ARVA.app quien abrió Docker Desktop, el aviso ofrece además **«Cerrar también Docker Desktop (lo abrió
  ARVA) para liberar memoria»**. La aplicación recuerda si se marcó o no para la próxima vez.

## Pasarle ARVA a otra persona

1. Enviarle el archivo **ARVA-mac.zip** (por AirDrop, un pendrive, correo o una carpeta compartida).
2. La otra persona instala **Docker Desktop** (<https://docs.docker.com/desktop/setup/install/mac-install/>), lo abre
   una vez y acepta sus condiciones. (Si no lo hace, ARVA.app se lo pide con un botón que abre esa página.)
3. Descomprime el zip, mueve **ARVA** a **Aplicaciones** y la abre la primera vez como se explica en
   [La primera vez que se abre](#la-primera-vez-que-se-abre).
4. ARVA.app le hace las preguntas del primer inicio en Terminal, descarga ARVA y lo abre. Listo.
5. Si más adelante quiere cambiar las respuestas (por ejemplo, guardar los datos en otro disco): menú
   **ARVA → Volver a configurar…**.

En una Mac que solo tiene Docker Desktop, ARVA.app no pide instalar nada más (tampoco las «herramientas de línea de
comandos» de Apple).

No necesita el código de ARVA, ni Git, ni una cuenta de GitHub, ni usar la terminal más allá de contestar esas
preguntas. Sus datos quedan en su Mac (o en el disco que elija): nada se comparte con quien le pasó la aplicación.

## Si ya se usaba ARVA desde la carpeta ARVA o con ARVA.command

ARVA.app usa **la misma instalación**: el mismo proyecto de Docker (`arva`), los mismos proyectos y bases de datos y
las mismas ubicaciones guardadas (`~/.config/arva/arva.conf`), así que no pregunta nada ni se pierde nada. Se puede
seguir usando `ARVA.command` cuando se quiera; no hay que usar los dos a la vez.

Dos diferencias:

- **El archivo `.env`.** Si en la carpeta del código había un archivo `.env` con ajustes propios (por ejemplo
  `ARVA_DB_PASSWORD`, la contraseña de la base de datos), ARVA.app lo usa también cuando esa carpeta es `~/ARVA`
  (pone en su carpeta un enlace a ese archivo; Detalles dice «Se usan los ajustes de ~/ARVA/.env»). Si la carpeta del
  código está en otro lugar, copiar ese `.env` a `~/Library/Application Support/ARVA/runtime/.env` (en Finder: menú
  Ir → Ir a la carpeta…, pegar esa ruta sin `.env`). Sin él, ARVA no podría entrar a su base de datos con la contraseña
  propia y diría «ARVA no responde».
- **La carpeta de importación por defecto** de ARVA.app es la suya
  (`~/Library/Application Support/ARVA/runtime/import`), no `ARVA/import` dentro de la carpeta del código. Si se
  eligió una carpeta de importación propia (por ejemplo en el disco externo), es la misma para los dos. El menú
  **Archivo → Abrir la carpeta de importación** abre siempre la que ARVA está usando en ese momento (también cuando
  ARVA se inició desde `~/ARVA`).

## Qué hacer cuando algo falla

Cuando algo sale mal, ARVA.app lo explica con un mensaje en palabras simples y tres botones: **Reintentar**,
**Copiar detalles** y **Salir** (y, cuando el problema es el disco, **Volver a configurar…** para elegir otro).
**Copiar detalles** copia todo lo que hizo el inicio, también lo que mostró la ventana de Terminal en el primer
inicio (la carpeta personal aparece como `~`); pegarlo (⌘V) en un correo o mensaje para quien ayuda con ARVA.
También está en el menú **Ayuda → Copiar detalles del inicio**.

| Mensaje | Qué hacer |
|---|---|
| **Conecta el disco** («El disco … no está conectado») | Conectar el disco externo donde están los datos, esperar a que aparezca en Finder y pulsar **Reintentar**. ARVA no se inicia sin él a propósito: así nunca escribe los datos en el disco interno. Para usar otro disco: **Volver a configurar…**. |
| **ARVA no llega a su disco** | El disco está conectado pero ARVA no puede usarlo. Casi siempre es porque se pulsó **No permitir** en el aviso de macOS: en **Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas → ARVA**, activar **Volúmenes extraíbles** y pulsar **Reintentar**. |
| **ARVA necesita Docker Desktop** | Instalarlo (botón **Descargar Docker Desktop**) y abrirlo una vez. |
| **Docker Desktop no terminó de abrirse** | Mirar la ventana de Docker Desktop: puede estar esperando que se acepten condiciones o una actualización. Cuando la ballena de la barra de menús deje de moverse, **Reintentar**. |
| **No se pudo descargar ARVA** | Revisar la conexión a internet y **Reintentar**. |
| **Docker Desktop no puede ver la carpeta** | En Docker Desktop: Settings → Resources → File sharing, añadir la carpeta (o el disco bajo `/Volumes`), **Apply**, y **Reintentar**. |
| **ARVA no se inició** (en el primer inicio) | Lo que pasó está en **Detalles** (y en la ventana de Terminal); corregirlo si dice cómo (por ejemplo, conectar el disco) y **Reintentar**. Si no está claro: **Copiar detalles** y enviarlo. |
| **Las preguntas no se terminaron** | Se cerró la ventana de Terminal (o se pulsó Control-C) antes de terminar. **Reintentar** las vuelve a mostrar. |
| **ARVA no se configuró** | En la última pregunta se eligió no guardar. **Responder de nuevo** vuelve a mostrar las preguntas. |
| **ARVA no responde** (dentro de la ventana) | Puede que Docker Desktop se haya cerrado. Abrirlo y pulsar **Reintentar** (o ⌘R). Si sigue, salir de ARVA.app y volver a abrirla. |
| macOS dice que **no se puede abrir** ARVA | Ver [La primera vez que se abre](#la-primera-vez-que-se-abre). |

Si nada de eso alcanza: **Copiar detalles** y enviarlos. Para más información técnica, `scripts/diagnostics.sh`
(en la carpeta del código, o en `~/Library/Application Support/ARVA/runtime/scripts`) imprime un informe completo
y [guia-mac.md](guia-mac.md), paso 11, explica los problemas más comunes.

**Volver a hacer las preguntas del primer inicio** (por ejemplo, para cambiar de disco): menú **ARVA → Volver a
configurar…**. Se abre Terminal con las mismas preguntas y ARVA se reinicia con las respuestas nuevas; no se mueve
ni se borra nada (las carpetas que se dejan de usar quedan como están).

**Desinstalar ARVA.app:** arrastrarla de Aplicaciones a la Papelera. Sus archivos de arranque están en
`~/Library/Application Support/ARVA` y se pueden borrar (sin tocar la carpeta `import` si tiene datos que interesen).
Los proyectos y las bases de datos no están ahí: están en el disco elegido o en Docker Desktop
([guia-mac.md](guia-mac.md), paso 15).

## Para quien la compila

- Código: `apps/mac/ARVA` (Swift, AppKit y WebKit de macOS, sin dependencias externas). Compilación:
  `scripts/build-mac-app.sh` (universal arm64 + x86_64, macOS 13 o posterior, versión = la de ARVA, firma *ad hoc*,
  `ARVA-mac.zip` con `ditto`). El flujo `.github/workflows/mac-app.yml` hace lo mismo en una Mac de GitHub, la
  verifica (arquitecturas, firma, Info.plist, archivos incluidos, `ARVA --self-test`) y guarda `ARVA-mac.zip`.
- La aplicación lleva dentro (copiados al compilar desde el repositorio) `docker-compose.yml`, `scripts/start.sh`,
  `scripts/stop.sh`, `scripts/lib/`, `scripts/metadata-backup.sh` y los demás archivos que necesita el lanzador. Al
  abrirse los copia a `~/Library/Application Support/ARVA/runtime` solo cuando cambiaron (y sin tocar nada más de esa
  carpeta) y ejecuta el lanzador desde allí, con `COMPOSE_PROJECT_NAME=arva`.
- Primer inicio: si no existe `~/.config/arva/arva.conf` (o con **ARVA → Volver a configurar…**), abre en Terminal un
  archivo `.command` que ejecuta `scripts/start.sh --setup` a través de `script(1)` (para guardar lo que muestra en
  `.first-run.log`, que pasa a Detalles), anota su proceso (`.first-run-pid`, para saber si se cerró la ventana y
  para detenerlo con Cancelar) y cómo terminó (`.first-run-status`: el estado de salida, `declined` si no se guardaron
  las respuestas, `interrupted`). Si existe, ejecuta `scripts/start.sh --no-setup` por detrás, con la salida en
  `~/Library/Application Support/ARVA/logs/start.log` (un archivo y no una tubería, así el inicio sigue aunque se
  salga de la aplicación). En ambos casos espera a que `http://localhost:8080/health` responda.
- Cancelar, **Detener y salir** durante el inicio y el límite de 20 minutos sin salida detienen el lanzador **y todo
  lo que inició** (`docker compose pull` / `up`), y esperan a que terminen antes de seguir.
- Delante en el `PATH` del lanzador van dos sustitutos que escribe la aplicación en
  `~/Library/Application Support/ARVA/bin`: `git` (responde a `rev-parse` con el commit de la aplicación, para que una
  Mac sin las herramientas de línea de comandos no muestre la ventana que ofrece instalarlas) y `open` (no vuelve a
  abrir `http://localhost:8080` en el navegador después de las preguntas; cualquier otra cosa la pasa a
  `/usr/bin/open`).
- Si la carpeta de arranque no tiene `.env` y existe `~/ARVA/.env`, la aplicación crea un enlace a ese archivo (nunca
  toca un `.env` propio de la carpeta de arranque).
- **Ayuda → Guía de ARVA para Mac** abre esta guía en GitHub tal como está en el commit con el que se compiló la
  aplicación.
- La ventana solo carga `http://localhost:8080` y `http://127.0.0.1:8080`; el resto de los enlaces va al navegador.
  No expone ningún puente de JavaScript a la página.
- `ARVA.app/Contents/MacOS/ARVA --self-test` comprueba la aplicación sin abrir ventanas ni tocar Docker.
