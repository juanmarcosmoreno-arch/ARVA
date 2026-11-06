# Plan: módulos por especie (más allá de *S. aureus*)

Estado: **propuesta para más adelante**. El usuario por ahora solo necesita *Staphylococcus*. Relevamiento hecho el
2026-11-06 sobre el código de ARVA y sobre fuentes primarias: la API de anaconda.org, los `meta.yaml` de
bioconda-recipes y los README y LICENSE de cada repositorio. No se instaló ni se ejecutó ninguna herramienta.

## 1. Qué es genérico hoy y qué no

**Ya sirve para cualquier bacteria:**
- ensamblado, pulido y anotación (Bakta, Prokka);
- especie con skani o FastANI contra la colección que se registre, y el constructor de colecciones de NCBI Datasets
  para cualquier taxón;
- MLST con los 162 esquemas de PubMLST que trae `mlst` 2.35.0;
- AMRFinderPlus, con mapeo automático de `--organism`;
- VFDB, MOB-suite, PlasmidFinder, IntegronFinder, ISEScan y geNomad;
- pangenoma, filogenia y variantes;
- la regla que detecta *lukF-PV* confundido con *lukD*: es genérica, solo el ejemplo del comentario es de
  *S. aureus*.

**Es propio de *S. aureus*, y está bien que lo sea:** SCCmec, spa, agr, la tarjeta de resumen MRSA/MSSA/PVL y las
advertencias de `staph_typing.py`.

**Supuestos de *S. aureus* que se filtraron al código genérico** (auditoría con archivo y línea en el historial de
la sesión):
- `tasks/typing.py:205`: el despachador de pasos solo conoce sccmec/spa/agr y busca por método, no por
  (módulo, método).
- `api/routes/typing.py:57`: rechaza cualquier módulo que no sea el de *S. aureus*. Además, el resumen y el CSV de
  proyecto siempre llaman a los de *S. aureus*.
- `schemas.py:3634`: `TypingMethod = Literal["sccmec","spa","agr"]`.
- Flujos: un nodo `staph_typing` propio, cableado en las plantillas genéricas. Toda especie recibe tres nodos que
  después se omiten.
- Informes: `reports.py` tiene la sección "Staphylococcus aureus typing" fija, y `project_report.py` agrupa por
  método sin tener en cuenta el módulo.
- Web: `lib/typing.ts` (`STAPH_MODULE`, `TYPING_METHODS`), y `StaphTyping.tsx` montado directamente en tres
  páginas.
- Aplicabilidad: compara la especie por igualdad exacta de texto. Un complejo de especies (*S. aureus*,
  *S. argenteus*, *S. schweitzeri*…) o un género no se pueden expresar.
- Sanger: la advertencia "16S no resuelve *Staphylococcus*" es un `if genus == "Staphylococcus"`. Debería ser una
  tabla de advertencias por género.

**Conclusión:** hoy agregar un módulo exige tocar unos 12 lugares del código. El registro (`typing_modules.py`)
está bien pensado, pero el resto no lo usa.

## 2. Propuesta: que un módulo sea casi solo datos

1. **Un único tipo de trabajo y un único nodo de flujo** `species_typing(module, step)`. El despacho pasa a ser por
   (módulo, paso), y la aplicabilidad y la omisión siguen siendo las de hoy.
2. **Aplicabilidad por taxón**: especie exacta, complejo o género. Cada módulo declara también cómo tratar a las
   especies vecinas: por ejemplo, "*S. argenteus*: se permite con advertencia".
3. **Cada paso declara** herramienta, lock de Bioconda, tipo de base de datos y un *parser* que entrega filas
   uniformes (campo, valor, confianza, evidencia). Las herramientas que comparten motor comparten adaptador: sccmec,
   pasty y pbptyper usan camlhmp, y un adaptador camlhmp sirve para los tres.
4. **Resumen, informe y CSV por módulo** a través de un registro. La web tiene un registro de tarjetas, con una
   tarjeta genérica, "tabla de resultados del módulo", para los módulos que no traen una propia.
5. **Advertencias de interpretación como datos**: reglas declaradas por el módulo o por el género, como la tabla de
   advertencias de Sanger o la colisión de nombres tipo *mecA*.
6. **Cada módulo trae su validación**: 10 a 20 genomas públicos con el resultado esperado, una prueba que los corre
   y una página de "validación del módulo" en la documentación. Eso es también lo que pediría una revista.

Primero se migra *S. aureus* a este esquema sin cambiar sus resultados (las pruebas actuales lo garantizan). Recién
después se agregan módulos nuevos.

## 3. *Staphylococcus* en general (lo que le sirve al laboratorio)

Comprobado:
- **MLST:** sale gratis. `mlst` 2.35.0 trae los esquemas `sepidermidis`, `shaemolyticus`, `shominis`,
  `schromogenes`, `staphlugdunensis` y `spseudintermedius`. Hay que pasar `--scheme` explícito porque
  `scheme_species_map.tab` tiene errores (por ejemplo "slugdunensis" frente a la carpeta "staphlugdunensis").
- ***S. argenteus* y *S. schweitzeri*** se tipifican con el esquema `saureus`; ARVA ya lo dice en
  `arva_core/species.py`.
- **AMRFinderPlus** tiene lógica por organismo (mutaciones puntuales y lista de exclusión) para *S. aureus*,
  *S. epidermidis* y *S. pseudintermedius* (`taxgroup.tsv` de la versión actual). Para *S. haemolyticus*,
  *S. capitis*, *S. lugdunensis* y *S. hominis* solo detecta genes.
- **sccmec 1.2.0** (MIT) corre sobre cualquier estafilococo, pero todas sus referencias son de *S. aureus*. En
  estafilococos coagulasa negativos (CoNS) conviene informar "clase mec + complejos ccr" con confianza baja, no un
  tipo de SCCmec.
- **AgrVATE** es explícitamente solo para *S. aureus*. **spa** tampoco aplica a CoNS; para *S. argenteus* se
  permitiría solo con advertencia.

Propuesta de un módulo "*Staphylococcus* no aureus":
- especie por ANI contra cepas tipo del género, incluyendo el complejo *S. aureus* y *Mammaliicoccus* (el grupo
  *sciuri*, reclasificado fuera de *Staphylococcus*);
- MLST con el esquema de la especie;
- *mecA*, *mecC* y *mecB*, con la advertencia de que en *Mammaliicoccus sciuri* los homólogos de *mecA* son
  intrínsecos;
- clase mec + ccr con confianza baja;
- marcadores por especie mediante una base curada para ABRicate. **Por verificar con bibliografía antes de
  implementarlo**: *ica*/IS256 en *S. epidermidis*, marcadores del clon NRCS-A en *S. capitis*, *fbl*/*vwbl* en
  *S. lugdunensis*, *lukI*/*siet*/*expA* en *S. pseudintermedius*. Hoy no hay una herramienta de Bioconda que
  cubra esto.

## 4. Otras especies: herramientas verificadas

Todas reciben un ensamblaje. "ARM Linux" se refiere a las imágenes linux-aarch64 de ARVA, que son las que usa
Docker en Mac M1/M2.

| Especie | Herramienta (Bioconda) | Licencia | ARM Linux | Nota |
|---|---|---|---|---|
| *Klebsiella pneumoniae* (complejo) | Kleborate 3.2.4 | GPL-3.0+ | sí | La "latest" es la beta 3.3.0b1: fijar la 3.2.4 |
| *Klebsiella* / *Acinetobacter baumannii* (cápsula K/O) | Kaptive 3.3.2 | GPL-3.0+ | sí | Las bases ya no vienen incluidas desde la 3.3.0 |
| *E. coli* (serotipo) | ECTyper 2.0.0 | Apache-2.0 | sí | |
| *E. coli* (filogrupo) | EzClermont 1.0.0 | MIT | sí | No necesita base de datos |
| *Salmonella* (serovar) | SISTR (sistr_cmd 1.1.3) | Apache-2.0 | sí | La base se descarga aparte (no debe bajarse sola) |
| *Haemophilus influenzae* (cápsula) | hicap 1.0.4 | GPL-3.0 | sí | |
| *Pseudomonas aeruginosa* (serogrupo O) | pasty 2.2.1 | Apache-2.0 | sí | camlhmp |
| *S. pneumoniae* (PBP) | pbptyper 2.0.0 | MIT | sí | camlhmp; CLI de la v2 por verificar |
| *N. gonorrhoeae* (NG-MAST/NG-STAR) | ngmaster 2.1.0 | GPL | sí | Licencia v2/v3 a aclarar |
| *M. tuberculosis* | TB-Profiler 6.7.0 | GPL-3.0+ | sí | La entrada FASTA solo está confirmada en el código fuente |

**No sirven en las imágenes ARM** porque dependen de isPcr, ariba o snippy, que no existen para linux-aarch64:
emmtyper, LisSero, meningotype, legsta, SeqSero2, SeroBA y ClermonTyping. Las cuatro primeras se usarían solo en
linux-64. SeroBA y PneumoCaT además necesitan lecturas, no ensamblajes, y PneumoKITy no está en Bioconda.

**Genéricas que más sumarían**, en orden:
1. **CheckM2**: completitud y contaminación antes de tipificar.
2. **chewBBACA 3.5.4** para cgMLST. Necesita un esquema; Chewie-NS no tiene uno de *Staphylococcus*, así que habría
   que adaptar uno y revisar su licencia.
3. **Distancias SNP y recombinación**, para brotes.
4. **ResFinder/PointFinder** (Apache-2.0) como segunda opinión de resistencia.
5. **RGI/CARD**: no es de código abierto (uso académico), así que no se integraría por defecto.
6. **GTDB-Tk 2.8.0**: solo linux-64, por pplacer.

## 5. Orden sugerido (cuando se decida)

1. Generalizar el marco (sección 2) migrando *S. aureus* sin cambiar resultados.
2. Módulo "*Staphylococcus* no aureus", que es el que usa el laboratorio.
3. Uno o dos módulos de gramnegativos con herramientas que corren en ARM (por ejemplo Kleborate + Kaptive y
   ECTyper + EzClermont), cada uno con su validación sobre genomas públicos.
