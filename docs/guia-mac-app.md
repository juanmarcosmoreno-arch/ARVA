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
informes que se descargan) o a un **disco externo** (donde están los datos). Hay que pulsar **Permitir**.

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
3. **La descarga.** Después ARVA descarga sus programas (varios GB, puede tardar un rato según la conexión).
   La ventana de Terminal lo va mostrando.
4. **ARVA se abre solo** en la ventana de ARVA.app cuando está listo. La ventana de Terminal ya se puede cerrar.

Las respuestas quedan guardadas: las veces siguientes no se pregunta nada.

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
    archivos y en ARVA usar **Importar datos → Importar desde una carpeta del servidor** (si en el primer inicio se
    eligió otra carpeta de importación, esa es la que vale).
- **Menús útiles:** **Visualización → Volver a cargar la página** (⌘R), **Ampliar / Reducir / Tamaño real**
  (⌘+, ⌘−, ⌘0), **Ver en el navegador** (⇧⌘B: abre la misma página en Safari u otro navegador), **Pantalla completa**.
  **Edición** tiene Copiar, Pegar y Seleccionar todo como siempre.
- La ventana recuerda su tamaño y posición.
- **Disco externo:** si los datos están en un disco externo, conectarlo **antes** de abrir ARVA.app.

## Salir: qué hace el aviso «¿Detener ARVA?»

Al salir (⌘Q, menú ARVA → Salir de ARVA, o cerrando la ventana) aparece **«¿Detener ARVA?»** con tres botones:

| Botón | Qué hace |
|---|---|
| **Detener y salir** (el resaltado; también con Enter) | Detiene ARVA (sus contenedores de Docker) para liberar la memoria que usa, y cierra la aplicación. Los proyectos, las bases de datos y los resultados **se conservan**; la próxima vez ARVA se inicia de nuevo. |
| **Salir sin detener** | Cierra solo la ventana: ARVA sigue funcionando por detrás (por ejemplo, para que termine un análisis largo). Se puede volver a abrir ARVA.app, o entrar en <http://localhost:8080> con el navegador. |
| **Cancelar** (o Esc) | No sale. |

- Si hay **análisis en curso o en espera**, el aviso lo dice: detener ARVA los interrumpe (se pueden volver a
  lanzar después). Para que terminen, elegir **Salir sin detener**.
- Si fue ARVA.app quien abrió Docker Desktop, el aviso ofrece además **«Cerrar también Docker Desktop (lo abrió
  ARVA) para liberar memoria»**. La aplicación recuerda si se marcó o no para la próxima vez.

## Pasarle ARVA a otra persona

1. Enviarle el archivo **ARVA-mac.zip** (por AirDrop, un pendrive, correo o una carpeta compartida).
2. La otra persona instala **Docker Desktop** (<https://docs.docker.com/desktop/setup/install/mac-install/>), lo abre
   una vez y acepta sus condiciones. (Si no lo hace, ARVA.app se lo pide con un botón que abre esa página.)
3. Descomprime el zip, mueve **ARVA** a **Aplicaciones** y la abre la primera vez como se explica en
   [La primera vez que se abre](#la-primera-vez-que-se-abre).
4. ARVA.app le hace las preguntas del primer inicio en Terminal, descarga ARVA y lo abre. Listo.

No necesita el código de ARVA, ni Git, ni una cuenta de GitHub, ni usar la terminal más allá de contestar esas
preguntas. Sus datos quedan en su Mac (o en el disco que elija): nada se comparte con quien le pasó la aplicación.

## Si ya se usaba ARVA desde la carpeta ARVA o con ARVA.command

ARVA.app usa **la misma instalación**: el mismo proyecto de Docker (`arva`), los mismos proyectos y bases de datos y
las mismas ubicaciones guardadas (`~/.config/arva/arva.conf`), así que no pregunta nada ni se pierde nada. Se puede
seguir usando `ARVA.command` cuando se quiera; no hay que usar los dos a la vez.

Una diferencia: la carpeta de importación por defecto de ARVA.app es la suya
(`~/Library/Application Support/ARVA/runtime/import`, menú **Archivo → Abrir la carpeta de importación**), no
`ARVA/import` dentro de la carpeta del código. Si se eligió una carpeta de importación propia (por ejemplo en el disco
externo), es la misma para los dos.

## Qué hacer cuando algo falla

Cuando algo sale mal, ARVA.app lo explica con un mensaje en palabras simples y tres botones: **Reintentar**,
**Copiar detalles** y **Salir**. **Copiar detalles** copia todo lo que hizo el inicio (la carpeta personal aparece
como `~`); pegarlo (⌘V) en un correo o mensaje para quien ayuda con ARVA. También está en el menú **Ayuda → Copiar
detalles del inicio**.

| Mensaje | Qué hacer |
|---|---|
| **Conecta el disco** («El disco … no está conectado») | Conectar el disco externo donde están los datos, esperar a que aparezca en Finder y pulsar **Reintentar**. ARVA no se inicia sin él a propósito: así nunca escribe los datos en el disco interno. |
| **ARVA necesita Docker Desktop** | Instalarlo (botón **Descargar Docker Desktop**) y abrirlo una vez. |
| **Docker Desktop no terminó de abrirse** | Mirar la ventana de Docker Desktop: puede estar esperando que se acepten condiciones o una actualización. Cuando la ballena de la barra de menús deje de moverse, **Reintentar**. |
| **No se pudo descargar ARVA** | Revisar la conexión a internet y **Reintentar**. |
| **Docker Desktop no puede ver la carpeta** | En Docker Desktop: Settings → Resources → File sharing, añadir la carpeta (o el disco bajo `/Volumes`), **Apply**, y **Reintentar**. |
| **ARVA no se inició** (en el primer inicio) | La ventana de Terminal dice qué pasó; corregirlo (por ejemplo, conectar el disco) y **Reintentar**. |
| **ARVA no responde** (dentro de la ventana) | Puede que Docker Desktop se haya cerrado. Abrirlo y pulsar **Reintentar** (o ⌘R). Si sigue, salir de ARVA.app y volver a abrirla. |
| macOS dice que **no se puede abrir** ARVA | Ver [La primera vez que se abre](#la-primera-vez-que-se-abre). |

Si nada de eso alcanza: **Copiar detalles** y enviarlos. Para más información técnica, `scripts/diagnostics.sh`
(en la carpeta del código, o en `~/Library/Application Support/ARVA/runtime/scripts`) imprime un informe completo
y [guia-mac.md](guia-mac.md), paso 11, explica los problemas más comunes.

**Volver a hacer las preguntas del primer inicio** (por ejemplo, para cambiar de disco): ver
[guia-mac.md](guia-mac.md); el lanzador (`scripts/start.sh --setup`) es el mismo.

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
- Primer inicio: si no existe `~/.config/arva/arva.conf`, abre en Terminal un archivo `.command` que ejecuta
  `scripts/start.sh --setup`; si existe, ejecuta `scripts/start.sh --no-setup` por detrás. En ambos casos espera a que
  `http://localhost:8080/health` responda.
- La ventana solo carga `http://localhost:8080` y `http://127.0.0.1:8080`; el resto de los enlaces va al navegador.
  No expone ningún puente de JavaScript a la página.
- `ARVA.app/Contents/MacOS/ARVA --self-test` comprueba la aplicación sin abrir ventanas ni tocar Docker.
