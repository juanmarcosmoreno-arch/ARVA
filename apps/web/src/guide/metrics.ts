/**
 * ARVA Guide — educational content for read-level metrics.
 *
 * Content rules (spec §22): explanations must be verifiable, describe how the
 * value is computed by ARVA, avoid universal good/bad thresholds and cite
 * primary literature or official documentation.
 */
import type { Language } from "@/store/settings";

export interface Reference {
  label: string;
  url: string;
}

interface Localized {
  title: string;
  what: string;
  why: string;
  how: string;
  interpret: string;
  next: string;
  mistakes: string[];
  limitations: string;
  advanced?: string;
}

export interface GuideEntry {
  id: GuideId;
  en: Localized;
  es: Localized;
  references: Reference[];
}

export type GuideId =
  | "fastq"
  | "integrity"
  | "read_count"
  | "length_distribution"
  | "n50"
  | "phred"
  | "read_quality"
  | "q20_q30"
  | "per_position_quality"
  | "quality_vs_length"
  | "gc_content"
  | "cumulative_yield"
  | "coverage"
  | "ambiguous";

const REF = {
  phred: { label: "Ewing & Green (1998) Genome Research 8:186–194 — Phred error probabilities", url: "https://doi.org/10.1101/gr.8.3.186" },
  fastq: { label: "Cock et al. (2010) Nucleic Acids Research 38:1767–1771 — The Sanger FASTQ format", url: "https://doi.org/10.1093/nar/gkp1137" },
  nanopack: { label: "De Coster et al. (2018) Bioinformatics 34:2666–2669 — NanoPack", url: "https://doi.org/10.1093/bioinformatics/bty149" },
  quast: { label: "Gurevich et al. (2013) Bioinformatics 29:1072–1075 — QUAST (N50/NG50 definitions)", url: "https://doi.org/10.1093/bioinformatics/btt086" },
  lander: { label: "Lander & Waterman (1988) Genomics 2:231–239 — coverage theory", url: "https://doi.org/10.1016/0888-7543(88)90007-9" },
  fastqc: { label: "FastQC documentation — analysis modules (Babraham Bioinformatics)", url: "https://www.bioinformatics.babraham.ac.uk/projects/fastqc/Help/3%20Analysis%20Modules/" },
  gcbias: { label: "Benjamini & Speed (2012) Nucleic Acids Research 40:e72 — GC-content bias", url: "https://doi.org/10.1093/nar/gks001" },
  iupac: { label: "Cornish-Bowden (1985) Nucleic Acids Research 13:3021–3030 — IUPAC nucleotide codes", url: "https://doi.org/10.1093/nar/13.9.3021" },
  sha: { label: "NIST FIPS 180-4 — Secure Hash Standard (SHA-256)", url: "https://doi.org/10.6028/NIST.FIPS.180-4" },
  wick: { label: "Wick, Judd & Holt (2019) Genome Biology 20:129 — Nanopore basecaller accuracy", url: "https://doi.org/10.1186/s13059-019-1727-y" },
} satisfies Record<string, Reference>;

export const GUIDE: GuideEntry[] = [
  {
    id: "fastq",
    references: [REF.fastq],
    en: {
      title: "FASTQ and FASTA files",
      what: "FASTQ stores sequencing reads: each record has an identifier, the DNA sequence and one quality character per base. FASTA stores sequences without qualities (often assemblies or references).",
      why: "Everything downstream (QC, assembly, annotation) starts from these files, so ARVA first checks that they are structurally correct.",
      how: "ARVA reads every record and checks: header starts with '@' (FASTQ) or '>' (FASTA), the '+' separator is present, sequence and quality have the same length, sequence characters are IUPAC nucleotide codes and quality characters are in the Phred+33 range. Compression (gzip) is detected from the file content, not its name.",
      interpret: "A validation error reports the exact line number. Most errors come from truncated transfers, files concatenated incorrectly or files that are not sequencing reads.",
      next: "If a file fails validation, re-transfer or regenerate it from the sequencer output and compare checksums with the source.",
      mistakes: ["Renaming a file to .fastq does not make it FASTQ.", "Multi-line FASTQ (legacy) is not supported; convert to 4-line records first."],
      limitations: "Read identifiers are not checked for uniqueness in this version.",
      advanced: "Quality strings are assumed to be Phred+33 (Sanger/Illumina 1.8+, ONT, PacBio). Legacy Phred+64 files pass structural validation but ARVA flags quality ranges that suggest the older encoding.",
    },
    es: {
      title: "Archivos FASTQ y FASTA",
      what: "FASTQ almacena lecturas de secuenciación: cada registro tiene un identificador, la secuencia y un carácter de calidad por base. FASTA almacena secuencias sin calidades (a menudo ensamblajes o referencias).",
      why: "Todo el análisis posterior parte de estos archivos, por eso ARVA comprueba primero que su estructura sea correcta.",
      how: "ARVA lee todos los registros y comprueba: encabezado con '@' (FASTQ) o '>' (FASTA), presencia del separador '+', igual longitud de secuencia y calidad, caracteres IUPAC válidos y calidades en el rango Phred+33. La compresión gzip se detecta por el contenido, no por el nombre.",
      interpret: "Un error de validación indica el número exacto de línea. La mayoría se debe a transferencias truncadas, concatenaciones incorrectas o archivos que no son lecturas.",
      next: "Si un archivo falla, vuelve a transferirlo o regenerarlo desde la salida del secuenciador y compara checksums con el original.",
      mistakes: ["Renombrar un archivo a .fastq no lo convierte en FASTQ.", "El FASTQ multilínea (antiguo) no está soportado; conviértelo a registros de 4 líneas."],
      limitations: "En esta versión no se comprueba que los identificadores de lectura sean únicos.",
      advanced: "Se asume codificación Phred+33. Los archivos Phred+64 antiguos pasan la validación estructural, pero ARVA advierte cuando el rango de calidades sugiere esa codificación.",
    },
  },
  {
    id: "integrity",
    references: [REF.sha],
    en: {
      title: "Checksums and data integrity",
      what: "A SHA-256 checksum is a 64-character fingerprint of a file's exact bytes. Any change to the file produces a different checksum.",
      why: "It proves that the data analysed is identical to the data received, and lets ARVA detect duplicate uploads.",
      how: "ARVA computes SHA-256 while the file is being stored. The original is saved read-only and never modified; all results are written elsewhere and linked back to it.",
      interpret: "Identical checksums mean identical files. Compare with the checksum provided by your sequencing facility, if available.",
      next: "Record the checksum in publications or data-sharing records to make the dataset verifiable.",
      mistakes: ["A gzip-compressed and an uncompressed copy of the same reads have different checksums."],
      limitations: "A checksum confirms identity, not biological quality.",
    },
    es: {
      title: "Checksums e integridad de datos",
      what: "Un checksum SHA-256 es una huella de 64 caracteres de los bytes exactos de un archivo. Cualquier cambio produce un checksum distinto.",
      why: "Demuestra que los datos analizados son idénticos a los recibidos y permite detectar cargas duplicadas.",
      how: "ARVA calcula SHA-256 mientras guarda el archivo. El original se almacena en modo solo lectura y nunca se modifica; los resultados se escriben aparte y se vinculan a él.",
      interpret: "Checksums idénticos significan archivos idénticos. Compáralo con el que proporcione tu servicio de secuenciación.",
      next: "Incluye el checksum en publicaciones o repositorios de datos para que el conjunto sea verificable.",
      mistakes: ["Una copia comprimida con gzip y otra sin comprimir de las mismas lecturas tienen checksums distintos."],
      limitations: "Un checksum confirma identidad, no calidad biológica.",
    },
  },
  {
    id: "read_count",
    references: [REF.nanopack],
    en: {
      title: "Number of reads and total bases",
      what: "Reads are the individual DNA fragments read by the sequencer. Total bases (yield) is the sum of all read lengths.",
      why: "Yield determines how much of the genome can be covered and how many times each position is read.",
      how: "ARVA counts every valid record and sums their lengths exactly; nothing is sampled.",
      interpret: "Compare yield with the expected genome size of your organism (see sequencing depth). For paired-end data, R1 and R2 are counted separately.",
      next: "If yield is lower than planned, consider whether more sequencing is needed before assembly.",
      mistakes: ["Counting bases from both mates and also the merged reads double-counts the same DNA."],
      limitations: "Yield includes any contaminating, host or adapter-derived sequence.",
    },
    es: {
      title: "Número de lecturas y bases totales",
      what: "Las lecturas son los fragmentos de ADN leídos por el secuenciador. Las bases totales (rendimiento) son la suma de sus longitudes.",
      why: "El rendimiento determina cuánto del genoma puede cubrirse y cuántas veces se lee cada posición.",
      how: "ARVA cuenta todos los registros válidos y suma sus longitudes de forma exacta; no hay muestreo.",
      interpret: "Compara el rendimiento con el tamaño esperado del genoma (ver profundidad). En paired-end, R1 y R2 se cuentan por separado.",
      next: "Si el rendimiento es menor de lo planificado, valora si hace falta secuenciar más antes de ensamblar.",
      mistakes: ["Sumar las bases de ambos mates y además de las lecturas fusionadas cuenta dos veces el mismo ADN."],
      limitations: "El rendimiento incluye secuencias contaminantes, del hospedador o derivadas de adaptadores.",
    },
  },
  {
    id: "length_distribution",
    references: [REF.nanopack, REF.fastqc],
    en: {
      title: "Read length distribution",
      what: "A histogram of how many reads fall in each length range.",
      why: "Long reads span repeats and help produce complete assemblies; for short-read data the distribution reveals trimming or library problems.",
      how: "ARVA records the exact length of every read and bins them. For long-read data spanning more than a 10-fold range, a log-spaced histogram is also produced. The 'bases' view weights each bin by the bases it contains.",
      interpret: "Illumina data usually show one sharp peak at the read length (or a spread after trimming). Nanopore and PacBio data show broad distributions shaped by DNA extraction and library preparation.",
      next: "Use the yield-by-length curve to decide whether a minimum-length filter would retain enough data.",
      mistakes: ["Judging long-read data by the number of reads rather than by the bases in long reads."],
      limitations: "Length alone says nothing about accuracy; check quality versus length.",
    },
    es: {
      title: "Distribución de longitudes de lectura",
      what: "Un histograma de cuántas lecturas caen en cada rango de longitud.",
      why: "Las lecturas largas atraviesan repeticiones y facilitan ensamblajes completos; en lecturas cortas la distribución revela recortes o problemas de librería.",
      how: "ARVA registra la longitud exacta de cada lectura y las agrupa. Cuando las longitudes abarcan más de un factor 10, se genera también un histograma con escala logarítmica. La vista 'bases' pondera cada intervalo por las bases que contiene.",
      interpret: "Illumina suele mostrar un pico estrecho en la longitud de lectura (o más disperso tras recortar). Nanopore y PacBio muestran distribuciones amplias que dependen de la extracción y de la librería.",
      next: "Usa la curva de rendimiento por longitud para decidir si un filtro de longitud mínima conservaría suficientes datos.",
      mistakes: ["Evaluar lecturas largas por el número de lecturas en vez de por las bases en lecturas largas."],
      limitations: "La longitud no informa sobre la exactitud; revisa calidad frente a longitud.",
    },
  },
  {
    id: "n50",
    references: [REF.quast, REF.nanopack],
    en: {
      title: "N50 and N90",
      what: "N50 is the length L such that reads of length ≥ L contain at least half of all bases. N90 uses 90 %.",
      why: "It summarises how much of the data is in long reads, which matters more than the average for long-read assembly.",
      how: "ARVA sorts read lengths from longest to shortest and accumulates bases until 50 % (or 90 %) of the total is reached. L50/L90 is the number of reads needed to get there.",
      interpret: "A higher read N50 means more of the yield is in long reads. For Illumina reads N50 equals the read length and is not informative.",
      next: "Compare read N50 with the length of repeats you expect in your organism (e.g. rRNA operons, insertion sequences).",
      mistakes: ["Comparing read N50 with assembly (contig) N50 — they describe different things.", "Using N50 alone: a few very long reads can raise it while most data stay short."],
      limitations: "N50 ignores read accuracy and can be changed substantially by length filtering.",
    },
    es: {
      title: "N50 y N90",
      what: "N50 es la longitud L tal que las lecturas de longitud ≥ L contienen al menos la mitad de todas las bases. N90 usa el 90 %.",
      why: "Resume cuánta información está en lecturas largas, algo más relevante que la media para ensamblar con lecturas largas.",
      how: "ARVA ordena las longitudes de mayor a menor y acumula bases hasta alcanzar el 50 % (o 90 %). L50/L90 es el número de lecturas necesarias.",
      interpret: "Un N50 mayor significa que más rendimiento está en lecturas largas. En Illumina el N50 coincide con la longitud de lectura y no aporta información.",
      next: "Compara el N50 con la longitud de las repeticiones esperadas (p. ej., operones de rRNA, secuencias de inserción).",
      mistakes: ["Comparar el N50 de lecturas con el N50 de un ensamblaje: describen cosas distintas.", "Usar solo el N50: unas pocas lecturas muy largas pueden elevarlo."],
      limitations: "El N50 ignora la exactitud y cambia mucho al filtrar por longitud.",
    },
  },
  {
    id: "phred",
    references: [REF.phred, REF.fastq],
    en: {
      title: "Phred quality scores",
      what: "Each base has a quality score Q that encodes the sequencer's estimated probability that the base is wrong: P(error) = 10^(−Q/10).",
      why: "Quality scores allow filtering and inform how much to trust each base.",
      how: "Q10 = 1 error in 10 (90 %), Q20 = 1 in 100 (99 %), Q30 = 1 in 1,000 (99.9 %), Q40 = 1 in 10,000. ARVA decodes them as Phred+33 characters.",
      interpret: "Scores are estimates produced by the basecaller; their calibration depends on the platform, chemistry and basecaller version.",
      next: "Record basecaller and model versions with your sample metadata: quality values are only comparable within the same pipeline.",
      mistakes: ["Averaging Q values directly (see mean read quality)."],
      limitations: "Phred scores are model estimates, not measured error rates.",
    },
    es: {
      title: "Puntuaciones de calidad Phred",
      what: "Cada base tiene una calidad Q que codifica la probabilidad estimada de error: P(error) = 10^(−Q/10).",
      why: "Permiten filtrar y saber cuánto confiar en cada base.",
      how: "Q10 = 1 error de cada 10 (90 %), Q20 = 1 de 100 (99 %), Q30 = 1 de 1.000 (99,9 %), Q40 = 1 de 10.000. ARVA las decodifica como caracteres Phred+33.",
      interpret: "Son estimaciones del basecaller; su calibración depende de la plataforma, la química y la versión del basecaller.",
      next: "Registra el basecaller y la versión del modelo en los metadatos: las calidades solo son comparables dentro de la misma cadena de procesamiento.",
      mistakes: ["Promediar directamente los valores Q (ver calidad media de lectura)."],
      limitations: "Las puntuaciones Phred son estimaciones de un modelo, no tasas de error medidas.",
    },
  },
  {
    id: "read_quality",
    references: [REF.phred, REF.nanopack, REF.wick],
    en: {
      title: "Mean read quality",
      what: "A single quality value summarising each read, and its distribution across all reads.",
      why: "It shows how many reads are likely to be accurate enough for your analysis.",
      how: "For each read ARVA converts every base Q to an error probability, averages those probabilities and converts the average back to a Phred value. This is the approach used by NanoPlot/NanoStat.",
      interpret: "Because the scale is logarithmic, a few low-quality bases strongly lower the read value; this is intentional and reflects the real expected number of errors. The distribution is more informative than a single mean.",
      next: "If you plan to filter by quality, check 'reads above Q' to see how much data each threshold would keep.",
      mistakes: ["Comparing mean read quality from tools that average Q values arithmetically — those are systematically higher."],
      limitations: "Reflects basecaller calibration; empirical accuracy requires alignment to a trusted reference.",
      advanced: "mean_Q(read) = −10·log10( (1/L)·Σ 10^(−Qi/10) ). 'Mean base quality' applies the same formula over all bases in the file. Median read quality is reported at 0.1 Q resolution.",
    },
    es: {
      title: "Calidad media de lectura",
      what: "Un valor de calidad que resume cada lectura, y su distribución en todas las lecturas.",
      why: "Muestra cuántas lecturas tienen probablemente la exactitud necesaria para tu análisis.",
      how: "Para cada lectura, ARVA convierte cada Q en probabilidad de error, promedia esas probabilidades y vuelve a convertir el promedio a escala Phred, como NanoPlot/NanoStat.",
      interpret: "Al ser una escala logarítmica, unas pocas bases de baja calidad bajan mucho el valor de la lectura; esto es intencional y refleja el número esperado real de errores. La distribución es más informativa que una media.",
      next: "Si piensas filtrar por calidad, revisa 'lecturas por encima de Q' para ver cuántos datos conservaría cada umbral.",
      mistakes: ["Comparar con herramientas que promedian los Q aritméticamente: dan valores sistemáticamente más altos."],
      limitations: "Refleja la calibración del basecaller; la exactitud empírica requiere alinear contra una referencia fiable.",
      advanced: "mean_Q(lectura) = −10·log10( (1/L)·Σ 10^(−Qi/10) ). La 'calidad media por base' aplica la misma fórmula a todas las bases. La mediana se reporta con resolución de 0,1 Q.",
    },
  },
  {
    id: "q20_q30",
    references: [REF.phred, REF.fastqc],
    en: {
      title: "Bases ≥ Q20 and ≥ Q30",
      what: "The percentage of all bases whose quality is at least Q20 (≤ 1 % error) or Q30 (≤ 0.1 % error).",
      why: "A compact summary widely used for short-read runs.",
      how: "ARVA counts every base's quality exactly and divides by the total number of bases with qualities.",
      interpret: "Expected values differ greatly by platform and chemistry. Compare with runs from the same instrument and kit rather than with a universal target.",
      next: "Look at the per-position plot to see whether low-quality bases are concentrated at read ends, where trimming may help.",
      mistakes: ["Applying Illumina Q30 expectations to Nanopore data."],
      limitations: "Base-level summaries hide whether errors are concentrated in a few reads.",
    },
    es: {
      title: "Bases ≥ Q20 y ≥ Q30",
      what: "Porcentaje de bases con calidad de al menos Q20 (≤ 1 % de error) o Q30 (≤ 0,1 %).",
      why: "Un resumen compacto muy usado para lecturas cortas.",
      how: "ARVA cuenta exactamente la calidad de cada base y divide por el total de bases con calidad.",
      interpret: "Los valores esperados varían mucho según plataforma y química. Compara con corridas del mismo equipo y kit, no con un objetivo universal.",
      next: "Mira el gráfico por posición para ver si las bases de baja calidad se concentran en los extremos, donde recortar puede ayudar.",
      mistakes: ["Aplicar expectativas de Q30 de Illumina a datos de Nanopore."],
      limitations: "Los resúmenes por base ocultan si los errores se concentran en pocas lecturas.",
    },
  },
  {
    id: "per_position_quality",
    references: [REF.fastqc],
    en: {
      title: "Quality by position in read",
      what: "The mean base quality at each position along the reads (position 1 = first base sequenced).",
      why: "Short-read chemistries typically lose quality towards the end of the read; this plot shows where.",
      how: "ARVA averages Phred values of all reads covering each position, up to the first 1,000 positions. The number of reads covering each position is also recorded.",
      interpret: "Most informative for fixed-length short reads. For long reads, few reads cover far positions and the curve mainly reflects read starts.",
      next: "If quality falls steeply at the 3′ end, quality trimming (e.g. fastp, coming in Phase 2) may be appropriate.",
      mistakes: ["Reading the tail of the curve without checking how many reads cover those positions."],
      limitations: "Arithmetic mean of Phred values per position (as in FastQC); this differs from the error-probability averaging used for read quality.",
    },
    es: {
      title: "Calidad por posición en la lectura",
      what: "La calidad media en cada posición de las lecturas (posición 1 = primera base secuenciada).",
      why: "En lecturas cortas la calidad suele bajar hacia el final; este gráfico muestra dónde.",
      how: "ARVA promedia los Phred de todas las lecturas que cubren cada posición, hasta las primeras 1.000. También registra cuántas lecturas cubren cada posición.",
      interpret: "Es más informativo para lecturas cortas de longitud fija. En lecturas largas, pocas lecturas cubren posiciones lejanas y la curva refleja sobre todo el inicio.",
      next: "Si la calidad cae mucho al final 3′, puede convenir un recorte por calidad (p. ej., fastp, previsto en la Fase 2).",
      mistakes: ["Interpretar la cola de la curva sin revisar cuántas lecturas cubren esas posiciones."],
      limitations: "Media aritmética de Phred por posición (como FastQC), distinta del promedio de probabilidades usado para la calidad por lectura.",
    },
  },
  {
    id: "quality_vs_length",
    references: [REF.nanopack],
    en: {
      title: "Quality versus length",
      what: "Each point is one read, placed by its length and mean quality.",
      why: "Shows whether the longest reads are also accurate, and reveals sub-populations (e.g. short, low-quality reads).",
      how: "ARVA plots a uniform random sample of reads (reservoir sampling with a recorded seed, so the plot is reproducible). All summary numbers use every read, not the sample.",
      interpret: "Look for clusters and trends rather than individual points.",
      next: "Combine with yield-by-length to choose length and quality filters together.",
      mistakes: ["Assuming the sample shows the exact number of outliers — it is a representative subset."],
      limitations: "Sampled view; rare read classes may be absent from the plot.",
    },
    es: {
      title: "Calidad frente a longitud",
      what: "Cada punto es una lectura, situada según su longitud y su calidad media.",
      why: "Muestra si las lecturas más largas también son exactas y revela subpoblaciones (p. ej., lecturas cortas de baja calidad).",
      how: "ARVA representa una muestra aleatoria uniforme de lecturas (muestreo reservoir con semilla registrada, reproducible). Todos los resúmenes usan todas las lecturas, no la muestra.",
      interpret: "Busca agrupaciones y tendencias más que puntos individuales.",
      next: "Combínalo con el rendimiento por longitud para elegir filtros de longitud y calidad a la vez.",
      mistakes: ["Suponer que la muestra muestra el número exacto de valores atípicos: es un subconjunto representativo."],
      limitations: "Vista muestreada; clases de lecturas raras pueden no aparecer.",
    },
  },
  {
    id: "gc_content",
    references: [REF.gcbias, REF.fastqc],
    en: {
      title: "GC content",
      what: "The percentage of G and C among unambiguous bases (A, C, G, T), overall and per read.",
      why: "Each species has a characteristic genomic GC content; the per-read distribution can hint at mixed sources or library bias.",
      how: "ARVA counts G+C over A+C+G+T(+U) for each read and for the whole file; ambiguous bases such as N are excluded.",
      interpret: "A single peak near the expected GC of your organism is consistent with one main source. Additional peaks may indicate contamination, plasmids with different composition, or bias — they are hints that require confirmation by taxonomic analysis.",
      next: "If the distribution is unexpected, plan species identification (Phase 5) before drawing conclusions.",
      mistakes: ["Treating a second GC peak as proof of contamination."],
      limitations: "Short reads give coarse per-read GC values; library preparation can shift the distribution.",
    },
    es: {
      title: "Contenido GC",
      what: "El porcentaje de G y C entre las bases no ambiguas (A, C, G, T), global y por lectura.",
      why: "Cada especie tiene un GC genómico característico; la distribución por lectura puede sugerir fuentes mezcladas o sesgos de librería.",
      how: "ARVA cuenta G+C sobre A+C+G+T(+U) en cada lectura y en el archivo; las bases ambiguas como N se excluyen.",
      interpret: "Un único pico cerca del GC esperado es consistente con una fuente principal. Picos adicionales pueden indicar contaminación, plásmidos de composición distinta o sesgos: son indicios que requieren confirmación taxonómica.",
      next: "Si la distribución es inesperada, planifica la identificación de especie (Fase 5) antes de sacar conclusiones.",
      mistakes: ["Tomar un segundo pico de GC como prueba de contaminación."],
      limitations: "Las lecturas cortas dan valores de GC por lectura poco precisos; la preparación de librería puede desplazar la distribución.",
    },
  },
  {
    id: "cumulative_yield",
    references: [REF.nanopack],
    en: {
      title: "Yield by minimum read length",
      what: "How many reads and bases would remain if only reads at least a given length were kept.",
      why: "Helps choose a length filter without discarding too much data.",
      how: "ARVA sorts reads from longest to shortest and accumulates reads and bases; the table lists common thresholds.",
      interpret: "A steep curve at short lengths means many short reads contribute few bases.",
      next: "Keep enough bases for your target depth after filtering; ARVA never filters silently.",
      mistakes: ["Choosing a filter by read count instead of retained bases."],
      limitations: "Does not account for quality; filtering by both changes the result.",
    },
    es: {
      title: "Rendimiento por longitud mínima",
      what: "Cuántas lecturas y bases quedarían si se conservaran solo las lecturas de al menos cierta longitud.",
      why: "Ayuda a elegir un filtro de longitud sin descartar demasiados datos.",
      how: "ARVA ordena las lecturas de mayor a menor y acumula lecturas y bases; la tabla muestra umbrales habituales.",
      interpret: "Una curva empinada en longitudes cortas significa que muchas lecturas cortas aportan pocas bases.",
      next: "Conserva suficientes bases para la profundidad objetivo tras filtrar; ARVA nunca filtra en silencio.",
      mistakes: ["Elegir un filtro por número de lecturas en vez de por bases conservadas."],
      limitations: "No tiene en cuenta la calidad; filtrar por ambas cambia el resultado.",
    },
  },
  {
    id: "coverage",
    references: [REF.lander],
    en: {
      title: "Approximate sequencing depth",
      what: "On average, how many times each base of the genome is expected to be sequenced: total bases ÷ genome size.",
      why: "Assembly and variant calling need enough depth; requirements depend on technology and goal.",
      how: "Only shown when you provide an expected genome size. ARVA divides total bases by that size.",
      interpret: "This is an upper-bound estimate: host DNA, contamination, plasmid copy number and uneven coverage all reduce the effective chromosomal depth.",
      next: "Measured coverage will be available after assembly or read mapping in later phases.",
      mistakes: ["Using the genome size of the wrong species or strain.", "Treating the estimate as uniform coverage."],
      limitations: "Not a measurement; it assumes all bases derive from the target genome.",
    },
    es: {
      title: "Profundidad aproximada de secuenciación",
      what: "Cuántas veces, en promedio, se espera secuenciar cada base del genoma: bases totales ÷ tamaño del genoma.",
      why: "El ensamblaje y la detección de variantes requieren profundidad suficiente; depende de la tecnología y del objetivo.",
      how: "Solo se muestra si indicas un tamaño de genoma esperado. ARVA divide las bases totales por ese tamaño.",
      interpret: "Es una estimación máxima: ADN del hospedador, contaminación, número de copias de plásmidos y cobertura desigual reducen la profundidad efectiva.",
      next: "La cobertura medida estará disponible tras el ensamblaje o el mapeo en fases posteriores.",
      mistakes: ["Usar el tamaño de genoma de otra especie o cepa.", "Interpretar la estimación como cobertura uniforme."],
      limitations: "No es una medición; asume que todas las bases proceden del genoma objetivo.",
    },
  },
  {
    id: "ambiguous",
    references: [REF.iupac],
    en: {
      title: "Ambiguous bases",
      what: "Bases other than A, C, G, T/U — mostly N (unknown), but any IUPAC ambiguity code counts.",
      why: "A high fraction can indicate basecalling problems, or masking in assemblies.",
      how: "ARVA counts every non-ACGTU character and reports the total and percentage of all bases.",
      interpret: "Raw reads usually contain few Ns. In FASTA assemblies, runs of N often represent gaps between scaffolded contigs.",
      next: "If unexpected, check the basecalling or assembly steps that produced the file.",
      mistakes: ["Including N in the GC denominator — ARVA excludes them."],
      limitations: "Position of ambiguous bases is not reported in this version.",
    },
    es: {
      title: "Bases ambiguas",
      what: "Bases distintas de A, C, G, T/U; principalmente N (desconocida), pero cuenta cualquier código IUPAC de ambigüedad.",
      why: "Una fracción alta puede indicar problemas de basecalling, o enmascaramiento en ensamblajes.",
      how: "ARVA cuenta todos los caracteres distintos de ACGTU y reporta el total y el porcentaje.",
      interpret: "Las lecturas crudas suelen tener pocas N. En ensamblajes FASTA, tramos de N suelen representar huecos entre contigs.",
      next: "Si es inesperado, revisa el basecalling o el ensamblaje que generó el archivo.",
      mistakes: ["Incluir las N en el denominador del GC: ARVA las excluye."],
      limitations: "En esta versión no se reporta la posición de las bases ambiguas.",
    },
  },
];

export const GUIDE_BY_ID = Object.fromEntries(GUIDE.map((g) => [g.id, g])) as Record<GuideId, GuideEntry>;

export function localized(entry: GuideEntry, language: Language): Localized {
  return entry[language] ?? entry.en;
}
