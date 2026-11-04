# Guía de instalación de ARVA en una Mac

Esta guía explica cómo instalar y usar ARVA en una Mac, con los proyectos y las bases de datos en un disco externo.
Está pensada para quien trabaja en microbiología y no necesita conocer Docker ni la terminal: cada paso dice qué
escribir y qué se debería ver. Los detalles técnicos completos están en [installation.md](installation.md) (en
inglés).

> **App para Mac.** Para usar ARVA como una aplicación (ícono en el Dock, ventana propia, arranque y apagado con un
> clic, y para pasársela a otra persona que solo tenga Docker Desktop) ver [guia-mac-app.md](guia-mac-app.md).

> **Estado.** El lanzador para Mac (`scripts/start.sh`, `ARVA.command`) se escribió a partir de la documentación de
> Apple y de Docker y se probó con programas simulados en Linux, **todavía no en una Mac real**. Si algo no coincide
> con lo que se ve en pantalla, ver el paso 11 (qué hacer cuando algo falla).

En los ejemplos, el disco externo se llama `JM` (en la Mac aparece como `/Volumes/JM`) y ya tiene una base de datos
completa de Bakta y una colección de genomas de referencia para FastANI en `/Volumes/JM/BioInf`. Con otro disco,
cambiar `JM` por su nombre.

## Contenido

1. [Requisitos](#1-requisitos)
2. [Instalar Docker Desktop](#2-instalar-docker-desktop)
3. [Ajustes de Docker Desktop](#3-ajustes-de-docker-desktop)
4. [Obtener el código de ARVA](#4-obtener-el-código-de-arva)
5. [Acceso a las imágenes: docker login ghcr.io](#5-acceso-a-las-imágenes-docker-login-ghcrio)
6. [Primer inicio con ARVA.command](#6-primer-inicio-con-arvacommand)
7. [La lista de primeros pasos](#7-la-lista-de-primeros-pasos)
8. [Registrar la base de datos completa de Bakta y la colección de FastANI](#8-registrar-la-base-de-datos-completa-de-bakta-y-la-colección-de-fastani)
9. [Base de datos de AMRFinderPlus](#9-base-de-datos-de-amrfinderplus)
10. [Un primer proyecto de prueba](#10-un-primer-proyecto-de-prueba)
    - [Lecturas Sanger de un gen (16S, toxinas, cualquier gen)](#lecturas-sanger-de-un-gen-16s-toxinas-cualquier-gen)
11. [Qué hacer cuando algo falla](#11-qué-hacer-cuando-algo-falla)
12. [Copias de seguridad](#12-copias-de-seguridad)
13. [Actualizar ARVA](#13-actualizar-arva)
14. [Detener ARVA](#14-detener-arva)
15. [Desinstalar](#15-desinstalar)

## 1. Requisitos

| Qué | Detalle |
|---|---|
| Mac | Con chip de Apple (M1, M2, M3, M4…) o con procesador Intel. Para saber cuál: menú Apple → **Acerca de esta Mac**: dice "Chip" (Apple) o "Procesador" (Intel). |
| macOS | Una versión que Docker Desktop admita: según Docker, la versión actual de macOS y las dos anteriores. La lista exacta está en la página de instalación de Docker Desktop (paso 2). |
| Memoria | Docker Desktop pide al menos 4 GB. ARVA elige su perfil de rendimiento según la Mac (paso 3); ensamblar y anotar con más memoria es más cómodo. |
| Docker Desktop | Gratuito para uso personal, educativo y en organizaciones pequeñas; las condiciones de uso las fija Docker (ver su página). |
| Disco externo | Formateado como **APFS** (o Mac OS Plus). **No usar exFAT ni FAT**: no guardan enlaces simbólicos ni permisos Unix, y la base de datos de Bakta contiene un enlace simbólico. Para ver el formato: Utilidad de Discos, o Finder → clic derecho en el disco → Obtener información → "Formato". |
| Espacio en el disco interno | Las imágenes de ARVA ocupan unos 16 GB (amd64) o 10 GB (arm64) dentro de la imagen de disco de Docker Desktop; reservar unos 20 GB más espacio para la versión siguiente mientras convive con la anterior. Se puede mover esa imagen de disco al disco externo (paso 3). |
| Espacio en el disco externo | Lo que ocupen los proyectos (lecturas, ensamblajes, resultados) y las bases de datos que descargue ARVA. La base completa de Bakta que ya existe no se copia: se usa donde está. |
| Internet | Para descargar Docker Desktop, el código y las imágenes de ARVA, y las bases de datos que se elijan descargar. Los análisis corren en la Mac: ARVA no envía lecturas, genomas ni resultados a ningún lado. |

## 2. Instalar Docker Desktop

1. Abrir <https://docs.docker.com/desktop/setup/install/mac-install/>.
2. Descargar la versión que corresponde: **Docker Desktop for Mac with Apple silicon** (chip de Apple) o **with
   Intel chip** (procesador Intel).
3. Abrir el archivo `Docker.dmg` descargado y arrastrar **Docker** a la carpeta **Aplicaciones**.
4. Abrir Docker desde Aplicaciones, aceptar sus condiciones y esperar a que el ícono de la ballena en la barra de
   menús (arriba a la derecha) quede quieto. No hace falta crear una cuenta de Docker.

Si falta este paso, el lanzador de ARVA lo detecta y muestra el mismo enlace.

## 3. Ajustes de Docker Desktop

Se abren desde el ícono de la ballena → **Settings** (Docker Desktop está en inglés). Después de cambiar algo, pulsar
**Apply & restart**.

### Recursos: CPU y memoria (Settings → Resources → Advanced)

Docker Desktop corre los programas de ARVA dentro de una máquina virtual Linux, y esa máquina solo usa la parte de
la Mac que se le asigna con **CPU limit** y **Memory limit**. ARVA elige un perfil de rendimiento según el modelo de
Mac y, al iniciarse, indica en la terminal y en **Ajustes → Rendimiento** si conviene cambiar estos valores. Su
recomendación (una regla de ARVA, no una medición):

| Mac | Perfil que elige ARVA | CPU limit | Memory limit |
|---|---|---|---|
| MacBook Air | Ligero | los hilos del perfil + 1 (como máximo las CPU lógicas de la Mac) | 50 % de la memoria de la Mac |
| MacBook Pro, Mac mini, iMac | Equilibrado | misma regla | 60 % |
| Mac Studio, Mac Pro | Máximo | misma regla | 75 % |

Por ejemplo, para una MacBook Pro con 8 núcleos de rendimiento, 2 de eficiencia y 16 GB, la recomendación es 7 CPU y
9 GB. No conviene dar a Docker tanta memoria que a macOS le quede menos de un cuarto.

### Imagen de disco en el disco externo (Settings → Resources → Advanced → Disk image location)

Docker Desktop guarda las imágenes y los contenedores en un único archivo de disco dentro de la Mac. Para no ocupar
el disco interno, elegir aquí una carpeta del disco externo (por ejemplo `/Volumes/JM/Docker`). **No mover ese
archivo con el Finder** (Docker lo desaconseja). Con la imagen de disco en el disco externo, Docker Desktop necesita
ese disco conectado para arrancar.

### Rosetta (solo Mac con chip de Apple; Settings → General)

ARVA publica dos imágenes:

- **amd64**: todas las herramientas (Bakta con todos sus pasos, Prokka, MOB-suite, IntegronFinder, AgrVATE, ISEScan,
  GTDB-Tk). En una Mac con chip de Apple corre traducida por Rosetta: funciona, pero más lenta que un programa nativo.
- **arm64**: nativa, pero sin las herramientas que no tienen versión arm64 (los pasos de CDS y ARN de Bakta, Prokka,
  MOB-suite, IntegronFinder, AgrVATE, ISEScan, GTDB-Tk).

Para anotar con Bakta completo conviene **amd64**, y para eso activar **"Use Rosetta for x86_64/amd64 emulation on
Apple Silicon"**. Sin ese ajuste, Docker emula amd64 con QEMU, mucho más lento. Si macOS no tiene Rosetta 2
instalado, se instala desde la Terminal con:

```bash
softwareupdate --install-rosetta --agree-to-license
```

En una Mac con Intel no hay nada que elegir: se usa amd64, nativa.

El lanzador lee este ajuste del archivo de ajustes de Docker Desktop
(`~/Library/Group Containers/group.com.docker/settings-store.json`). En la Mac de prueba ese archivo **solo guardaba
los ajustes cambiados respecto de los valores por omisión**: no tenía ninguna entrada de Rosetta aunque Rosetta estaba
activado en la ventana de Docker Desktop. En ese caso el lanzador dice que el archivo no guarda el ajuste (no que
algo haya fallado), usa igualmente la imagen amd64 y pide comprobar en Docker Desktop que esté activado.

### Carpetas compartidas (Settings → File sharing; en algunas versiones Settings → Resources → File sharing)

Docker Desktop comparte por omisión `/Users`, `/Volumes`, `/private`, `/tmp` y `/var/folders`. Con esa lista un
disco externo se puede montar, pero **el espacio libre que ve ARVA es el de otro disco**. Comprobado en una MacBook
Air M2 con Docker Desktop y el disco externo `JM` (datos en `/Volumes/JM/ARVA/data`):

- Con la lista por omisión, dentro del contenedor la carpeta de datos venía de `/run/host_mark/Volumes` y
  `df -h /data` mostraba **229 GB con 8,6 GB libres: el disco de arranque de la Mac**, mientras que en la Mac el
  disco `JM` tenía 931,5 GB con 57,3 GB libres. Los controles de espacio de ARVA (y el aviso "Quedan menos de 20 GB
  libres" de la lista de primeros pasos) usaban así el disco equivocado.
- Quitando `/Volumes` **sin** agregar el disco, Docker no inicia ARVA: "mounts denied: The path
  /Volumes/JM/ARVA/data is not shared from the host and is not known to Docker".
- Agregando `/Volumes/JM` y quitando `/Volumes`, `df -h /data` muestra `/run/host_mark/Volumes/JM`, 932 GB, 58 GB
  libres: el disco correcto.

No se sabe todavía si funciona dejar `/Volumes` **y** agregar `/Volumes/JM` (una prueba no fue concluyente). Por eso:
**compartir el propio disco y quitar `/Volumes`**:

1. Docker Desktop → **Settings** → **File sharing**.
2. Pulsar **+**, luego **Cmd+Shift+G**, escribir `/Volumes/JM` (el nombre del disco) y **Abrir**.
3. Seleccionar `/Volumes` en la lista y quitarlo (**−**).
4. **Apply** (o **Apply & restart**) y volver a abrir `ARVA.command`.

Repetir el paso 2 para cada disco externo que use ARVA (por ejemplo, si `BioInf` está en otro disco; también el
disco de la carpeta `ARVA` si no está en la carpeta de usuario, porque su carpeta `import` también se monta). El
lanzador lee la lista de Docker Desktop de su archivo de ajustes (sin modificarlo nunca), revisa cada carpeta y, si
el disco solo llega por `/Volumes` (o por `/`) o por la lista por omisión, lo explica y en el primer inicio espera a
que se cambie. Además, una vez en marcha, ARVA compara el tamaño del disco que ve dentro de Docker con el que midió
el lanzador en la Mac y revisa de qué carpeta compartida viene cada montaje: si es otro disco, **Ajustes →
Almacenamiento** (y la lista de primeros pasos, para las carpetas en las que ARVA escribe) muestran el aviso "Docker
muestra el espacio libre de otro disco" con estos pasos, y los controles de espacio usan la cifra que midió el
lanzador al iniciar **menos lo que ARVA escribió desde entonces** en sus carpetas de ese disco (lo que escriban otros
programas en el disco no se cuenta). Ese cálculo sigue valiendo si Docker Desktop reinicia los contenedores, por
ejemplo al reiniciar la Mac; volver a abrir `ARVA.command` mide de nuevo y no reinicia los trabajos en marcha.

El nombre con que Docker Desktop guarda esa lista en su archivo de ajustes no se ha visto todavía: en la Mac de la
prueba, con la lista por omisión, el archivo no tenía ninguna entrada de carpetas compartidas. Si el lanzador sigue
avisando después de cambiarla, lo que vale es lo que muestra **Ajustes → Almacenamiento** una vez iniciado ARVA.

## 4. Obtener el código de ARVA

El código está en GitHub: <https://github.com/juanmarcosmoreno-arch/ARVA>. Hay dos formas; la primera facilita las
actualizaciones.

### Opción A: git clone (recomendada)

1. Abrir la **Terminal** (Aplicaciones → Utilidades → Terminal).
2. La primera vez que se escribe `git`, macOS puede ofrecer instalar las "herramientas de línea de comandos"
   (Command Line Tools): aceptar y esperar a que termine.
3. Ir a la carpeta donde se quiere el programa (el programa ocupa poco; puede quedar en el disco interno) y clonar:

```bash
cd ~
git clone https://github.com/juanmarcosmoreno-arch/ARVA.git
cd ARVA
```

Si el repositorio es **privado**, git pide usuario y contraseña de GitHub. La contraseña **no** es la de la cuenta:
es un **token de acceso personal**. Para crearlo: GitHub → foto de perfil → **Settings → Developer settings →
Personal access tokens**:

- *Fine-grained token*: dar acceso de solo lectura al repositorio ARVA (permiso **Contents: Read-only**), o
- *Tokens (classic)*: marcar el permiso **repo**.

Copiar el token (GitHub lo muestra una sola vez) y pegarlo cuando git pida la contraseña. La Mac puede guardarlo en
el llavero. Si el repositorio es público, git no pide nada.

Si quien mantiene ARVA indica una rama distinta de la principal, agregarla al clonar, por ejemplo
`git clone -b <rama> https://github.com/juanmarcosmoreno-arch/ARVA.git` (a la fecha de esta guía el desarrollo está
en la rama `claude/affectionate-darwin-oknu0k`).

### Opción B: descargar el ZIP

En la página del repositorio (con la sesión de GitHub iniciada si es privado): botón verde **Code → Download ZIP**,
abrirlo con doble clic y mover la carpeta resultante a donde se quiera (por ejemplo la carpeta personal). Con un
archivo descargado por el navegador, macOS puede bloquear `ARVA.command` la primera vez (ver el paso 6). Si al abrirlo
dice que no tiene permiso de ejecución, escribir en la Terminal, dentro de la carpeta de ARVA:

```bash
chmod +x ARVA.command "Detener ARVA.command"
```

## 5. Acceso a las imágenes: docker login ghcr.io

ARVA no se compila en la Mac: descarga dos imágenes ya construidas y probadas por GitHub Actions,
`ghcr.io/juanmarcosmoreno-arch/arva-api` y `ghcr.io/juanmarcosmoreno-arch/arva-web`. Al escribir esta guía
(3 de noviembre de 2026) GitHub las muestra como **públicas**, así que no hace falta iniciar sesión; su dueño puede
volverlas privadas. **Si son privadas**, iniciar sesión una vez en cada Mac:

1. Crear un token de acceso personal *classic* con el permiso **read:packages** (GitHub → Settings → Developer
   settings → Personal access tokens → Tokens (classic) → Generate new token).
2. En la Terminal:

```bash
docker login ghcr.io -u <usuario de GitHub>
```

3. Cuando pida **Password**, pegar el token (no se ve mientras se pega) y pulsar Enter. Debe decir
   `Login Succeeded`.

Docker guarda el token en su propio almacén de credenciales (en la Mac, el llavero); ARVA nunca lo ve, lo guarda ni
lo envía. Si se olvida este paso, el lanzador lo detecta cuando la descarga es rechazada y ofrece hacerlo en ese
momento.

## 6. Primer inicio con ARVA.command

1. Conectar el disco externo `JM`.
2. Abrir Docker Desktop (el lanzador también lo abre si está cerrado).
3. En el Finder, abrir la carpeta de ARVA y hacer **doble clic en `ARVA.command`**. Se abre una ventana de Terminal.

**Permisos de macOS la primera vez:**

- Si macOS dice que no puede abrir `ARVA.command` porque es de un desarrollador no identificado (pasa con archivos
  descargados con el navegador): clic derecho sobre `ARVA.command` → **Abrir** → **Abrir**; en las versiones
  recientes de macOS, si no aparece esa opción, ir a **Ajustes del Sistema → Privacidad y seguridad** y pulsar
  **Abrir igualmente** junto al aviso de `ARVA.command`. Solo hace falta una vez.
- Si macOS pregunta si **Terminal** puede acceder a archivos de un **volumen extraíble** (el disco externo):
  responder **Permitir**. Se puede revisar en Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas.

**Las preguntas del primer inicio.** La primera vez, el lanzador hace unas preguntas, en español si la Mac está en
español. En cada una, **Enter** acepta lo que está entre corchetes:

1. **Docker Desktop**: comprueba que está instalado y en marcha (si está cerrado, lo abre y espera).
2. **Dónde guardar proyectos y bases de datos**: muestra los discos conectados con su formato y espacio libre, por
   ejemplo:

   ```
   Discos conectados a esta computadora:
      1) JM · APFS · 1650.2 GB libres de 1863.0 GB
      -  Macintosh HD · APFS · 286.1 GB libres de 476.8 GB (el disco de arranque de la Mac)
   ```

   Al elegir `1` propone `/Volumes/JM/ARVA/data` (proyectos, resultados, informes, registros y copias de seguridad) y
   `/Volumes/JM/ARVA/databases` (bases de datos que descargue ARVA), y las crea si no existen. `0` guarda todo dentro
   de Docker Desktop (no recomendado si se quiere el disco externo).
3. **Bases de datos que ya existen**: escribir (o arrastrar desde el Finder a la ventana) `/Volumes/JM/BioInf` y
   pulsar Enter; luego Enter vacío para seguir. Esa carpeta se usa **en solo lectura**: ARVA nunca escribe, mueve ni
   borra nada en ella. Opcionalmente, una carpeta con corridas de secuenciación para importar (también solo
   lectura).
4. **Arquitectura de las imágenes** (solo chip de Apple): `1` amd64 (todas las herramientas; recomendada) o `2`
   arm64. Si el ajuste de Rosetta de Docker Desktop está desactivado o el archivo de ajustes no lo guarda, explica
   cómo comprobarlo y espera.
5. **Carpetas compartidas**: si una carpeta elegida está en un disco externo que Docker Desktop solo comparte a
   través de `/Volumes` (o con la lista por omisión), explica por qué conviene compartir el disco mismo y cómo
   (paso 3, carpetas compartidas), espera a que se pulse Enter y vuelve a leer la lista.

Antes de guardar muestra un **Resumen** con todo lo que se va a guardar: las carpetas de datos y de bases de datos,
las carpetas de bases de datos existentes y la carpeta para importar («ninguna» si se pasó la pregunta con Enter) y
la arquitectura de las imágenes. Si falta algo (por ejemplo, `/Volumes/JM/BioInf`), contestar que no y volver a
responder. Después pregunta **¿Guardar estas elecciones e iniciar ARVA? [S/n]**. Las respuestas quedan en
`~/.config/arva/arva.conf`; no se vuelven a preguntar. Para responderlas de nuevo:
`scripts/start.sh --setup` (en la Terminal, dentro de la carpeta de ARVA) o, en ARVA.app, **ARVA → Volver a
configurar…**. Esa segunda vez, las respuestas sobre el disco y la arquitectura reemplazan las guardadas (con `0`,
«dentro de Docker Desktop», el resumen avisa que la carpeta guardada antes deja de usarse; no se mueve ni se borra
nada de ella), mientras que las carpetas de bases de datos existentes y la carpeta para importar guardadas antes se
conservan si se pasa la pregunta con Enter: se listan al llegar a esa pregunta y el resumen las marca «guardada
antes, se conserva». Para dejar de usar una carpeta de bases de datos: `scripts/start.sh --remove-databases RUTA`.

Si las preguntas se cortan antes del final (se cerró la ventana, se pulsó Control-C o Control-D), lo dice
(«Las respuestas terminaron antes de que se respondieran todas las preguntas» o «Las preguntas se
interrumpieron») y no guarda nada.

Luego descarga las imágenes, inicia ARVA, muestra el perfil de rendimiento y
las ubicaciones, y **abre el navegador en <http://localhost:8080>**. La primera descarga de cada versión avisa
antes cuánto ocupa: unos 16 GB ya descomprimidas (amd64; 10 GB arm64), la descarga misma es menor porque viene
comprimida; con una conexión lenta puede tardar más de una hora (en la prueba en una Mac, 1,5 h a unos 0,8 MB/s).
Al actualizar desde una versión anterior suele ser bastante menos: Docker reutiliza las partes que ya tiene, y el
aviso lo dice. La ventana de Terminal puede cerrarse al final
(pulsar Enter): ARVA sigue funcionando en Docker Desktop.

ARVA solo escucha en la propia Mac (`127.0.0.1`): no es accesible desde otras computadoras de la red.

**Los inicios siguientes**: doble clic en `ARVA.command` otra vez (con el disco `JM` conectado). Si el disco no está
conectado, ARVA no se inicia y lo dice, para no escribir nada en el disco interno por error.

**Sin doble clic**, desde la Terminal en la carpeta de ARVA, hace lo mismo:

```bash
scripts/start.sh --open
```

Las opciones de siempre siguen funcionando sin preguntas, por ejemplo
`scripts/start.sh --data-dir /Volumes/JM/ARVA/data --databases-dir /Volumes/JM/ARVA/databases --add-databases /Volumes/JM/BioInf`
(`--no-setup` evita las preguntas en cualquier caso).

## 7. La lista de primeros pasos

En **Inicio**, ARVA muestra la lista **Primeros pasos**. Cada punto muestra el estado que informa ARVA en ese
momento (no se marca a mano):

| Punto | Listo cuando |
|---|---|
| Ubicaciones de almacenamiento | la carpeta de datos está en el disco externo y todas las carpetas están conectadas |
| Perfil de rendimiento | ARVA reconoció la Mac (iniciado con `ARVA.command` o `scripts/start.sh`) y los recursos de Docker Desktop le sirven |
| Base de datos de Bakta | hay una base de Bakta registrada o instalada y legible |
| Colección de genomas de referencia | hay una colección registrada (para FastANI y skani) |
| Base de datos de AMRFinderPlus | hay una versión instalada |
| Primer proyecto | existe al menos un proyecto |

Cada punto pendiente tiene un botón que lleva al lugar donde se resuelve. **Ocultar** la quita; **Ajustes →
Interfaz → Mostrar la lista de primeros pasos en Inicio** la vuelve a mostrar.

## 8. Registrar la base de datos completa de Bakta y la colección de FastANI

Las dos ya están en `/Volumes/JM/BioInf`, que se agregó en solo lectura en el primer inicio (si no se agregó:
`scripts/start.sh --add-databases /Volumes/JM/BioInf` y volver a iniciar ARVA).

### Bakta (base completa)

1. **Herramientas y bases → Bases de datos de referencia → Registrar carpeta existente…**
2. Recorrer la carpeta agregada (`/Volumes/JM/BioInf`) hasta la carpeta de la base de Bakta: la que contiene
   `version.json` (si se elige la carpeta superior donde escribió `bakta_db download`, ARVA reconoce la base en sus
   subcarpetas y la ofrece).
3. ARVA reconoce el tipo, lee la versión de `version.json` y hace una **verificación rápida** (que estén los archivos;
   no escribe nada en la carpeta). Pulsar **Registrar**.
4. Opcional: la **suma de comprobación completa** (SHA-256 de cada archivo) corre en segundo plano y se puede cancelar;
   sobre una base completa en un disco USB puede tardar horas.

Para que Bakta anote las CDS también necesita una base de AMRFinderPlus reciente (paso 9): la copia que viene dentro
de algunas bases de Bakta (por ejemplo la liviana 6.0) es más antigua de lo que acepta AMRFinderPlus 4.2.7; los
detalles están en [installation.md](installation.md#bakta-and-prokka-genome-annotation).

### Colección de genomas de referencia (FastANI)

1. **Registrar carpeta existente…** otra vez.
2. Elegir la carpeta del **paquete de NCBI Datasets** extraído (la que contiene `ncbi_dataset/` y `md5sum.txt`) o la
   **lista de FastANI** (`.txt`, una ruta de genoma por línea). Las rutas escritas como en la Mac
   (`/Volumes/JM/BioInf/...`) se traducen solas; una ruta fuera de las carpetas agregadas se rechaza.
3. El paquete de NCBI no registra la fecha de descarga: escribirla (ARVA sugiere la fecha del zip si está al lado).
   ARVA muestra cuántos genomas, especies, material tipo y genomas de referencia tiene la colección.

Después, en la pestaña **Análisis genómico** de una muestra, la identificación de especie puede usar FastANI o skani
con esta colección.

## 9. Base de datos de AMRFinderPlus

En **Herramientas y bases**, en AMRFinderPlus, elegir una versión publicada por NCBI y descargarla. Antes de descargar,
ARVA muestra el tamaño y las condiciones; al terminar la indexa. Se guarda en la carpeta de bases de datos
(`/Volumes/JM/ARVA/databases`). Es la única de estas tres bases que hay que descargar.

## 10. Un primer proyecto de prueba

Para probar sin usar datos propios, conviene un conjunto **público y pequeño**. Una opción usada en las pruebas de
ARVA: lecturas Illumina de *S. aureus* JKD6159 (ST93), corrida **SRR21386014** (BioSample SAMN02604217), cuyo genoma
completo de referencia es GCF_000144955.2.

1. Ver los archivos y sus sumas MD5 en ENA: abrir
   <https://www.ebi.ac.uk/ena/portal/api/filereport?accession=SRR21386014&result=read_run&fields=fastq_ftp,fastq_md5,fastq_bytes>
   (muestra los dos archivos `_1.fastq.gz` y `_2.fastq.gz`, su tamaño en bytes y su MD5).
2. Descargarlos (por ejemplo a `/Volumes/JM/lecturas/`) desde los enlaces `fastq_ftp` (agregar `https://` delante) y
   comprobar la suma en la Terminal: `md5 SRR21386014_1.fastq.gz` debe dar el mismo valor que `fastq_md5`.
3. Opcional, para una prueba más rápida, un **subconjunto** (las primeras 350.000 lecturas de cada archivo; cada
   lectura FASTQ son 4 líneas):

   ```bash
   gzip -cd SRR21386014_1.fastq.gz | head -n 1400000 | gzip > SRR21386014_subset_350k_1.fastq.gz
   gzip -cd SRR21386014_2.fastq.gz | head -n 1400000 | gzip > SRR21386014_subset_350k_2.fastq.gz
   ```

   Dejarlo escrito en la descripción de la muestra ("primeras 350.000 lecturas de SRR21386014"): es un subconjunto,
   no la corrida completa, y los resultados (cobertura, contigs) lo reflejan.
4. En ARVA: **Nuevo proyecto** (por ejemplo "Prueba JKD6159"), agregar una muestra (organismo *Staphylococcus
   aureus*, corrida SRR21386014), **Importar datos** y elegir los dos archivos.
5. Seguir el recorrido: control de calidad, filtrado, ensamblaje, anotación con Bakta, MLST (JKD6159 es ST93),
   especie, resistencia (AMRFinderPlus) y tipificación de *S. aureus*.

Para lecturas de Oxford Nanopore (R10.4.1) el pulido puede hacerse con **Medaka** (estrategia "Lecturas de Oxford
Nanopore: Medaka" del diálogo de pulido), como en el pipeline habitual Filtlong → Flye → Medaka. ARVA lee el modelo de
basecalling de las cabeceras de las lecturas (por ejemplo `dna_r10.4.1_e8.2_400bps_sup@v5.2.0`) y, con la
correspondencia propia de medaka, propone el modelo de Medaka (`r1041_e82_400bps_sup_v5.2.0`). Solo se usan los
modelos que trae el paquete de Medaka 2.1.1 (sup y hac v5.2.0): no hay nada que descargar ni registrar. Medaka viene
dentro de la imagen (aproximadamente 1,6 GB más) y usa la CPU; con 3,8 GB para Docker Desktop, si se queda sin
memoria, bajar el tamaño de lote (-b) en el diálogo.

**Flye necesita unos 9 GB de memoria dentro de Docker, sean cuales sean las lecturas.** Flye 2.9.6 reserva al
empezar una tabla fija de k-mers de 8 GiB (`src/sequence/vertex_index.cpp`, k = 17 en todas sus configuraciones);
medido con 413 Mb de lecturas simuladas, el pico fue de 8,8 GB, y en la Mac de prueba, con 5,9 GB en el contenedor,
Flye se quedó sin memoria con y sin `--asm-coverage`. `--asm-coverage` no baja ese piso. En una Mac de 8 GB, Docker
Desktop no puede darle tanta memoria: el diálogo de Flye lo dice ("Flye no puede ejecutarse en esta computadora con
la configuración actual") y no ofrece `--asm-coverage`. En ese caso se puede ensamblar con Flye fuera de ARVA y
agregar el genoma con "Registrar un FASTA de genoma…". Con memoria suficiente para ese piso, el diálogo estima
además, con la cifra que documenta Flye (2 GB para *E. coli* a 50×), si las lecturas caben en la memoria que tiene
el contenedor y, si no, ofrece el botón
**Usar --asm-coverage 40** (Flye documenta `--asm-coverage` para usar menos memoria y su manual dice que 40× de las
lecturas más largas suele bastar; necesita un tamaño de genoma). En los
flujos "Genoma bacteriano, análisis completo" y "Ensamblaje Nanopore", la **protección de memoria de Flye** hace lo mismo sola
cuando la estimación no cabe y la muestra tiene un tamaño de genoma esperado; lo deja registrado en la ejecución y
nunca cambia un valor que el paso fija por sí mismo. Se puede apagar en las opciones de la ejecución. En esas mismas
opciones se elige la estrategia de pulido de la ejecución (por ejemplo Medaka).

Una nota sobre Prokka: Prokka nombra al gen *mecA* como `pbp` (su producto es la PBP2a); ARVA no cambia lo que
escribe la herramienta, pero lo aclara donde corresponde. Bakta y AMRFinderPlus lo llaman *mecA*.

### Lecturas Sanger de un gen (16S, toxinas, cualquier gen)

Para identificar un gen secuenciado por Sanger (por ejemplo los `.ab1` que devuelve Macrogen):

1. En **Herramientas y bases**, en "ARN ribosómico 16S de NCBI (cepas tipo)", **Descargar la compilación actual**
   (unos 73 MB; ARVA muestra antes la fecha, el tamaño y el MD5 y pide confirmar). Hace falta solo para nombrar
   lecturas de 16S; VFDB, los alelos MLST y AMRFinderPlus ya están.
2. Abrir la muestra de la cepa (si no existe, crearla) y su pestaña **Sanger**. Arrastrar los dos `.ab1`, la lectura
   directa y la reversa, por ejemplo `…cepa12_784-F.ab1` y `…cepa12_1401-R.ab1`: ARVA propone la dirección, el cebador y
   el par por el nombre, y se pueden cambiar.
3. Revisar cada **Cromatograma**: la región conservada por el recorte (de una lectura de más de 1.500 bases llamadas suelen quedar unas 550 a 600 útiles) y las
   bases que conviene revisar.
4. En **Identificar**, **Previsualizar el consenso**, revisar los conflictos si los hay, escribir si se quiere lo que
   se sospecha (gen o especie) y **Guardar la identificación**.
5. **Buscar en las fuentes locales**, revisar el resumen y confirmar. Al terminar se ven las coincidencias ordenadas
   con identidad, cobertura y la versión de cada base, la lectura del 16S con sus criterios y si coincide lo que se
   sospechaba. El informe se descarga en español o en inglés.

Todo se hace en el Mac: ARVA no envía las secuencias a NCBI. El BLAST en línea de NCBI es un paso manual y opcional,
con su aviso. Con el fragmento 784F–1401R del 16S, *Staphylococcus* suele quedar en género: ARVA lo dice y sugiere
genes de mayor resolución (*rpoB*, *sodA*, *tuf*, *gap*).

## 11. Qué hacer cuando algo falla

ARVA nunca envía nada por su cuenta. Para pedir ayuda, se copia un informe y se envía por el medio que se prefiera
(correo, chat). Los informes no contienen secuencias, lecturas, contenido de archivos, contraseñas, tokens, correos
electrónicos ni el número de serie de la Mac; la carpeta personal aparece como `~`.

- **Un análisis falló**: en el panel del trabajo, **Copiar detalles del error**. Copia el informe de ese trabajo
  (pegarlo en el mensaje).
- **Un error en la interfaz**: el aviso muestra un código como `K7Q2-M9XD`; **Ajustes → Diagnóstico** lista los
  errores recientes y tiene **Copiar informe de diagnóstico** (texto listo para pegar) y **Descargar** (un zip para
  adjuntar). La casilla **Sustituir los nombres de proyectos, muestras y archivos por project-1, sample-1, file-1**
  oculta esos nombres en el informe.
- **La interfaz no abre o Docker no arranca**: en la Terminal, dentro de la carpeta de ARVA:

  ```bash
  scripts/diagnostics.sh --output informe-arva.md
  ```

  Escribe el informe en `informe-arva.md` (versión de ARVA, ubicaciones y sus discos, versiones de Docker, estado de
  los servicios, últimos errores y últimas líneas de cada contenedor, todo depurado del mismo modo). Adjuntar ese
  archivo.

Problemas frecuentes:

| Se ve | Qué hacer |
|---|---|
| "Docker Desktop no está instalado" | paso 2 |
| "Docker Desktop no estuvo listo en 180 s" | abrir Docker Desktop, esperar a que la ballena quede quieta y volver a abrir `ARVA.command` |
| "Docker no pudo descargar … read:packages" | paso 5 (o revisar la conexión a internet) |
| "La carpeta de datos … no está en el disco en el que estaba" o "¿está conectado su disco?" | conectar el disco `JM` y volver a abrir `ARVA.command` |
| "mounts denied: The path /Volumes/… is not shared from the host and is not known to Docker" | se quitó `/Volumes` de File sharing sin agregar el disco: agregar `/Volumes/<Disco>` (paso 3, carpetas compartidas) |
| "Docker muestra el espacio libre de otro disco", o "Quedan menos de 20 GB libres" aunque el disco externo tiene más | Docker Desktop comparte el disco solo a través de `/Volumes`: agregar `/Volumes/<Disco>` y quitar `/Volumes` (paso 3) |
| "El archivo de ajustes de Docker Desktop no guarda el ajuste de Rosetta" | no es un error: comprobar en Docker Desktop → Settings → General que Rosetta esté activado (paso 3) |
| Un trabajo dice que el sistema lo detuvo con SIGKILL | casi siempre falta memoria: elegir un perfil más liviano en Ajustes → Rendimiento o dar más memoria a Docker Desktop (paso 3) y volver a iniciar ARVA |
| Pulido con Pilon sin memoria (OutOfMemoryError) | la documentación de Pilon pide al menos 8 GB para un genoma bacteriano con ~200x de Illumina (16 GB recomendados). ARVA le da por omisión hasta lo que puede usar una herramienta menos 1 GB, que deja para el consumo propio de Java y los demás servicios de ARVA (2 GB cuando Docker Desktop tiene 3,8 GB), y lo avisa en el diálogo de pulido: dar más memoria a Docker Desktop (paso 3) |
| Pulido con Medaka sin memoria (el trabajo dice que el sistema detuvo Medaka) | bajar el tamaño de lote (-b, por omisión 100; según medaka "controla el uso de memoria") en el diálogo de pulido, o dar más memoria a Docker Desktop (paso 3) |
| Medaka pide elegir el modelo | ARVA no encontró el modelo de basecalling en las cabeceras de las lecturas (o no corresponde a un modelo que trae Medaka): elegir el modelo que corresponde al basecalling con el que se generaron las lecturas, o pulir con Racon |
| Todo muy lento en una Mac con chip de Apple | activar Rosetta en Docker Desktop (paso 3) |

## 12. Copias de seguridad

- **Archivos** (lecturas, ensamblajes, resultados, informes): están en `/Volumes/JM/ARVA/data`. Hacer copia de ese
  disco como de cualquier otro (por ejemplo a un segundo disco).
- **Metadatos** (proyectos, muestras, trabajos y ajustes): están en una base de datos dentro de Docker Desktop. ARVA
  copia esos metadatos a `/Volumes/JM/ARVA/data/backups/` automáticamente cada 24 horas y en el primer inicio, y
  guarda las 14 más recientes de cada tipo. Así el disco externo tiene los archivos **y** sus metadatos.
- **Copia en el momento**: Ajustes → Almacenamiento → **Hacer una copia ahora**, o en la Terminal `scripts/backup.sh`.
- **Restaurar** (deshacer un error, o usar el disco en otra Mac):

  ```bash
  scripts/restore.sh --list      # las copias, de la más nueva a la más vieja
  scripts/restore.sh latest      # restaura la más reciente (pide confirmación)
  ```

  Antes de restaurar hace una copia de los metadatos actuales; no toca los archivos de la carpeta de datos.

## 13. Actualizar ARVA

- **Con git** (opción A): en la Terminal, dentro de la carpeta de ARVA, `git pull`, y luego doble clic en
  `ARVA.command`.
- **Con ZIP** (opción B): descargar el ZIP nuevo, reemplazar la carpeta del programa y abrir `ARVA.command`.

Al iniciar, el lanzador descarga las imágenes de la versión nueva y ARVA actualiza sus metadatos solo. Las
ubicaciones guardadas (`~/.config/arva/arva.conf`), los proyectos del disco externo y los metadatos de Docker Desktop
se conservan. Para estar seguros, hacer antes una copia de los metadatos (paso 12).

## 14. Detener ARVA

Doble clic en **`Detener ARVA.command`** (o `scripts/stop.sh` en la Terminal). Detiene y quita los contenedores; los
proyectos, las bases de datos, los metadatos y las imágenes se conservan, y se vuelve a iniciar con `ARVA.command`.
Antes de desconectar el disco externo, detener ARVA. Cerrar Docker Desktop también lo detiene.

## 15. Desinstalar

1. Detener ARVA (paso 14) y hacer una última copia de los metadatos si se quieren conservar (paso 12).
2. Borrar las imágenes (Docker Desktop → **Images**, o en la Terminal):

   ```bash
   docker image ls | grep arva
   docker image rm <nombre:etiqueta de cada imagen de ARVA>
   ```

3. Borrar los metadatos dentro de Docker Desktop (**esto borra los proyectos y muestras registrados**; las copias en
   `/Volumes/JM/ARVA/data/backups/` permiten recuperarlos después):

   ```bash
   docker volume ls | grep arva
   docker volume rm arva_postgres-data arva_arva-data arva_arva-databases
   ```

   (`docker volume ls` muestra los nombres exactos; los dos últimos solo tienen contenido si alguna vez se guardaron
   datos dentro de Docker Desktop).
4. Borrar las ubicaciones guardadas: `rm -r ~/.config/arva`
5. Borrar la carpeta del programa (por ejemplo `~/ARVA`).
6. Los datos del disco externo (`/Volumes/JM/ARVA`) y la carpeta `/Volumes/JM/BioInf` **no se tocan**: borrarlos a
   mano solo si ya no se necesitan.
7. Si ya no se usa Docker Desktop, se desinstala desde su propio menú (Troubleshoot → Uninstall) o arrastrándolo a
   la papelera.
