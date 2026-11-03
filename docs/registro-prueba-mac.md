# Registro de la prueba en la Mac del usuario

Problemas y mejoras detectados durante la instalación y la primera prueba real de ARVA en una MacBook Air M2
(8 GB, macOS 27.0.1, Docker Desktop, disco externo APFS `/Volumes/JM`), con la cepa 27 (barcode04, GridION,
R10.4.1 SUP v5.2.0) comparada contra el pipeline propio del usuario. Cada punto dice qué se vio, el estado y, si
ya se resolvió, en qué commit.

Estados: **resuelto** · **en curso** · **pendiente** · **idea** (mejora a evaluar).

## Instalación

| # | Qué se vio | Estado |
|---|---|---|
| 1 | Con el uso compartido por omisión de Docker Desktop (`/Volumes`), dentro de los contenedores el espacio libre de `/Volumes/JM` aparecía como el del disco interno (8,6 GB en vez de 57 GB). Se arregló compartiendo `/Volumes/JM` y quitando `/Volumes`. | resuelto (e61eaef): detección, aviso, cifras medidas en la Mac y guía |
| 2 | El arranque decía "No se pudo leer el ajuste de Rosetta" aunque Rosetta estaba activado: Docker solo guarda en `settings-store.json` los ajustes cambiados. | resuelto (e61eaef) |
| 3 | El resumen del arranque llamaba "volumen de Docker" a la carpeta de importación `./import`. | resuelto (e61eaef) |
| 4 | En el asistente de primer inicio se pasó la pregunta de bases existentes con Enter y `/Volumes/JM/BioInf` no quedó agregada; no hubo un resumen final que lo mostrara antes de guardar. | pendiente: mostrar el resumen completo (incluidas las carpetas de bases, o "ninguna") antes de "¿Guardar?" |
| 5 | El primer intento del asistente terminó en la pregunta de la imagen y volvió a la terminal sin mensaje; el segundo intento funcionó. | pendiente: investigar (posible EOF en la lectura) |
| 6 | La descarga de la imagen amd64 tardó 1,5 h (~0,8 MB/s). | idea: avisar el tamaño y el tiempo estimado antes de descargar |
| 7 | El ícono de ARVA.app se ve borroso (logo de 164 px). | pendiente: falta el logo en alta resolución |
| 8 | Al cerrar Docker Desktop, ARVA dejó de responder y Safari mostró solo "Load failed". | pendiente: mensaje claro en la interfaz ("ARVA no responde: ¿Docker Desktop está abierto?"); ARVA.app ya abre Docker |

## Interfaz

| # | Qué se vio | Estado |
|---|---|---|
| 9 | La interfaz arrancó en inglés aunque la Mac está en español. | pendiente: elegir el idioma del navegador/sistema en la primera visita |
| 10 | Al registrar la colección de referencia, la fecha escrita como 27/05 quedó guardada como 2026-05-07. | pendiente: mostrar la fecha interpretada en palabras antes de "Registrar" y revisar el campo de fecha |
| 11 | "Primeros pasos" quedó en "Leyendo el perfil de rendimiento…" hasta recargar la página. | pendiente: investigar |
| 12 | En "Nuevo ensamblaje" quedó elegido el archivo original aunque existía el filtrado, y al reabrir la ventana se borró el tipo de lectura. | pendiente: preseleccionar el archivo filtrado más reciente y conservar las elecciones |
| 13 | La colección de referencia muestra 68 especies; el recuento previo del usuario decía 82 (probablemente subespecies). | idea: mostrar especies y subespecies por separado |
| 14 | Cambiar la carpeta de importación exige la terminal (`--import-dir`). | idea: elegirla desde Ajustes o desde ARVA.app |

## Herramientas y análisis

| # | Qué se vio | Estado |
|---|---|---|
| 15 | Las versiones de Debian no coinciden con las del pipeline del usuario: Flye 2.9.1 (usuario 2.9.6) y Filtlong 0.2.1 (usuario 0.3.1). | en curso: fijar Flye 2.9.6 y Filtlong 0.3.1 desde Bioconda |
| 16 | Falta Medaka (el usuario pule con Medaka 2.1.1, modelo `r1041_e82_400bps_sup_v5.2.0`). | en curso: Medaka como estrategia de pulido |
| 17 | La tipificación de *S. aureus* (spa, SCCmec, agr) no está en la plantilla de flujo "Genoma bacteriano completo". | en curso |
| 18 | Para lotes largos, la Mac no debe suspenderse. | en curso: ARVA.app evita el reposo mientras haya análisis |
| 19 | Flye se quedó sin memoria con 147× (413 Mb) en los 3,8 GB de Docker (el usuario lo corrió nativo con los 8 GB de la Mac). | pendiente: antes de lanzar, estimar si la cobertura cabe en la memoria y sugerir `--asm-coverage` con tamaño de genoma (opción documentada por Flye); usarlo por omisión en lotes sobre Macs de 8 GB |
| 20 | Pilon recibía 1 GB de heap (el manual pide ~1 GB por Mb). | resuelto (e61eaef): heap dentro de la memoria disponible y aviso |
| 21 | Las lecturas de la cepa 27 muestran un pico de longitud cerca de 3–3,6 kb y un segundo pico de GC ~43 %: compatible con el control DCS de lambda de ONT (sin confirmar). | idea: detectar y señalar lecturas o contigs del control DCS |
| 22 | ARVA sugiere `--nano-hq` para estas lecturas (error medio 0,72 %); el pipeline del usuario usó `--nano-raw`. | idea: documentar la comparación de ambos modos |
