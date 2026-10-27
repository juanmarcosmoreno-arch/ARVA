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
  | "ambiguous"
  | "filtering"
  | "fastp"
  | "filtlong"
  | "crosscheck"
  | "fastqc_flags"
  | "before_after";

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
  fastp: { label: "Chen et al. (2018) Bioinformatics 34:i884–i890 — fastp", url: "https://doi.org/10.1093/bioinformatics/bty560" },
  filtlong: { label: "Filtlong documentation (R. Wick) — method and read scoring", url: "https://github.com/rrwick/Filtlong" },
  seqkit: { label: "Shen et al. (2016) PLoS ONE 11:e0163962 — SeqKit", url: "https://doi.org/10.1371/journal.pone.0163962" },
  fastqcHome: { label: "FastQC project page and documentation (Babraham Bioinformatics)", url: "https://www.bioinformatics.babraham.ac.uk/projects/fastqc/" },
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
  {
    id: "filtering",
    references: [REF.fastp, REF.filtlong],
    en: {
      title: "Read filtering and trimming",
      what: "Removing reads (filtering) or parts of reads (trimming) that are unlikely to be useful: very short reads, low-quality reads, adapter sequence left over from library preparation.",
      why: "Poor reads and adapters can fragment assemblies and create false variants. But every removed read is information lost, so filtering is a trade-off, not a default.",
      how: "ARVA runs established tools (fastp for short reads, Filtlong for long reads). Every threshold is shown before running and recorded in the exact command line. Original files are never changed: the kept reads are saved as a new derived file linked to its parent.",
      interpret: "Compare before and after: how many reads and bases were kept, and how the length and quality distributions changed. Large losses deserve a reason.",
      next: "Use the filtered file for downstream analyses only if the comparison shows the trade-off is acceptable for your goal; the original stays available.",
      mistakes: ["Filtering aggressively 'just in case' and losing coverage of difficult regions.", "Forgetting which file (original or filtered) was used later — check the lineage shown for each file."],
      limitations: "Filtering decisions depend on technology, chemistry, genome and purpose; ARVA does not choose thresholds for you.",
      advanced: "fastp short-read filters apply per read/pair; Filtlong ranks whole reads by a combined length/quality score and keeps the best subset.",
    },
    es: {
      title: "Filtrado y recorte de lecturas",
      what: "Eliminar lecturas (filtrado) o partes de lecturas (recorte) que probablemente no sean útiles: lecturas muy cortas, de baja calidad o con restos de adaptadores de la librería.",
      why: "Las lecturas malas y los adaptadores pueden fragmentar ensamblajes y crear variantes falsas. Pero cada lectura eliminada es información perdida: filtrar es un compromiso, no un paso automático.",
      how: "ARVA ejecuta herramientas establecidas (fastp para lecturas cortas, Filtlong para largas). Todos los umbrales se muestran antes de ejecutar y quedan registrados en la línea de comando exacta. Los archivos originales nunca se modifican: las lecturas conservadas se guardan como un archivo derivado nuevo, vinculado a su origen.",
      interpret: "Compara antes y después: cuántas lecturas y bases se conservaron y cómo cambiaron las distribuciones de longitud y calidad. Las pérdidas grandes necesitan una justificación.",
      next: "Usa el archivo filtrado solo si la comparación muestra que el compromiso es aceptable para tu objetivo; el original sigue disponible.",
      mistakes: ["Filtrar agresivamente «por si acaso» y perder cobertura de regiones difíciles.", "Olvidar qué archivo (original o filtrado) se usó después: revisa el linaje de cada archivo."],
      limitations: "Las decisiones de filtrado dependen de la tecnología, la química, el genoma y el objetivo; ARVA no elige los umbrales por ti.",
      advanced: "Los filtros de fastp actúan por lectura/par; Filtlong ordena lecturas completas por una puntuación combinada de longitud y calidad y conserva el mejor subconjunto.",
    },
  },
  {
    id: "fastp",
    references: [REF.fastp],
    en: {
      title: "fastp (short reads)",
      what: "A fast preprocessor for Illumina-type reads that trims adapters, filters reads by quality, N content and length, and writes an HTML/JSON report.",
      why: "Adapter read-through and low-quality reads are common in short-read libraries; fastp handles both in one pass, for single-end or paired-end data.",
      how: "Adapters are detected automatically (for paired-end data by overlapping the two mates). A read is removed when more than the allowed percentage of its bases are below the 'qualified' quality, when it has too many N, or when it ends up shorter than the minimum length. For pairs, both mates are removed together.",
      interpret: "The 'removed because' counts show which filter acted. Adapter-trimmed reads are kept (shorter), not removed.",
      next: "If many reads are lost to one filter, review that threshold rather than the others.",
      mistakes: ["Running fastp on Nanopore/PacBio reads — it is designed for short reads.", "Assuming fastp does nothing by default: without options it already filters (Q15, 40 % unqualified, 5 N, 15 bp) — ARVA always passes these values explicitly."],
      limitations: "Automatic adapter detection can miss rare or custom adapters; poly-G trimming is applied automatically only for two-colour instruments (NextSeq/NovaSeq) unless forced or disabled.",
      advanced: "Defaults verified from `fastp --help` (0.23.4): --qualified_quality_phred 15, --unqualified_percent_limit 40, --n_base_limit 5, --length_required 15, --average_qual 0 (off).",
    },
    es: {
      title: "fastp (lecturas cortas)",
      what: "Un preprocesador rápido para lecturas tipo Illumina que recorta adaptadores, filtra lecturas por calidad, contenido de N y longitud, y genera un informe HTML/JSON.",
      why: "Los restos de adaptador y las lecturas de baja calidad son frecuentes en librerías de lecturas cortas; fastp trata ambos en una pasada, para datos single-end o paired-end.",
      how: "Los adaptadores se detectan automáticamente (en paired-end, solapando los dos mates). Una lectura se elimina si supera el porcentaje permitido de bases por debajo de la calidad «aceptable», si tiene demasiadas N o si queda más corta que la longitud mínima. En pares, ambos mates se eliminan juntos.",
      interpret: "Los recuentos «eliminadas por» muestran qué filtro actuó. Las lecturas con adaptador recortado se conservan (más cortas), no se eliminan.",
      next: "Si se pierden muchas lecturas por un filtro, revisa ese umbral antes que los demás.",
      mistakes: ["Usar fastp con lecturas Nanopore/PacBio: está diseñado para lecturas cortas.", "Suponer que fastp no hace nada por defecto: sin opciones ya filtra (Q15, 40 % no aceptables, 5 N, 15 pb). ARVA siempre pasa estos valores explícitamente."],
      limitations: "La detección automática puede no encontrar adaptadores raros o personalizados; el recorte poli-G solo se aplica automáticamente en equipos de dos colores (NextSeq/NovaSeq) salvo que se fuerce o desactive.",
      advanced: "Valores por defecto verificados en `fastp --help` (0.23.4): --qualified_quality_phred 15, --unqualified_percent_limit 40, --n_base_limit 5, --length_required 15, --average_qual 0 (desactivado).",
    },
  },
  {
    id: "filtlong",
    references: [REF.filtlong],
    en: {
      title: "Filtlong (long reads)",
      what: "A filter for Nanopore and PacBio reads that removes reads failing hard thresholds and can keep only the best part of the data.",
      why: "Long-read sets often contain many short or low-accuracy reads that add little to an assembly.",
      how: "Hard thresholds (minimum/maximum length, minimum mean or window quality) remove reads outright. 'Keep percent' and 'target bases' then keep the best-scoring reads, measured in bases, using a score that combines length and quality. Reads are kept or dropped whole.",
      interpret: "Filtlong quality thresholds are percent identities, not Phred: 90 means 90 % expected accuracy ≈ Q10, 95 ≈ Q13, 99 ≈ Q20. ARVA shows the Phred equivalent next to the value.",
      next: "Check the yield curve before and after: target bases is ideal to cap very large datasets while keeping the longest, most accurate reads.",
      mistakes: ["Typing a Phred value (e.g. 10) as --min_mean_q — that would mean 10 % identity and remove almost nothing.", "Using 'keep percent' as a read-count fraction — it is measured in bases."],
      limitations: "Without an external reference, quality comes from the basecaller's Phred scores, whose calibration varies.",
      advanced: "Mean identity = 100 × (1 − mean per-base error probability), so identity X ⇔ Q = −10·log10(1 − X/100) — the same error-averaged quality ARVA reports per read.",
    },
    es: {
      title: "Filtlong (lecturas largas)",
      what: "Un filtro para lecturas Nanopore y PacBio que elimina lecturas que no superan umbrales y puede conservar solo la mejor parte de los datos.",
      why: "Los conjuntos de lecturas largas suelen contener muchas lecturas cortas o poco exactas que aportan poco al ensamblaje.",
      how: "Los umbrales duros (longitud mínima/máxima, calidad media o de ventana mínima) eliminan lecturas directamente. Después, «porcentaje a conservar» y «bases objetivo» conservan las lecturas con mejor puntuación, medidas en bases, usando una puntuación que combina longitud y calidad. Las lecturas se conservan o eliminan completas.",
      interpret: "Los umbrales de calidad de Filtlong son identidades porcentuales, no Phred: 90 significa 90 % de exactitud esperada ≈ Q10, 95 ≈ Q13, 99 ≈ Q20. ARVA muestra el equivalente Phred junto al valor.",
      next: "Revisa la curva de rendimiento antes y después: «bases objetivo» es ideal para limitar conjuntos muy grandes conservando las lecturas más largas y exactas.",
      mistakes: ["Escribir un valor Phred (p. ej., 10) como --min_mean_q: significaría 10 % de identidad y casi no eliminaría nada.", "Interpretar «porcentaje a conservar» como fracción de lecturas: se mide en bases."],
      limitations: "Sin referencia externa, la calidad proviene de las puntuaciones Phred del basecaller, cuya calibración varía.",
      advanced: "Identidad media = 100 × (1 − probabilidad media de error por base), así que identidad X ⇔ Q = −10·log10(1 − X/100), la misma calidad promediada por error que ARVA reporta por lectura.",
    },
  },
  {
    id: "crosscheck",
    references: [REF.seqkit],
    en: {
      title: "Independent cross-check (SeqKit)",
      what: "The same file is summarised by a second, independent program (SeqKit) and the results are compared metric by metric with ARVA's own statistics.",
      why: "Agreement between two independent implementations is strong evidence that the numbers are correct; a disagreement points to a bug or an edge case worth investigating.",
      how: "Counts and lengths must match exactly. Mean length and percentages are allowed only the difference caused by SeqKit's rounding. Quartiles are not compared because some SeqKit versions report them incorrectly; GC is compared only when the file has no ambiguous bases.",
      interpret: "All metrics agreeing means ARVA's statistics were reproduced independently. Any 'differs' row is reported, never hidden.",
      next: "If a metric differs, note both tool versions and report it; do not rely on that metric until resolved.",
      mistakes: ["Expecting identical decimals from tools that round differently."],
      limitations: "Two tools can share the same misunderstanding of a malformed file; ARVA's validation step guards against that separately.",
    },
    es: {
      title: "Verificación independiente (SeqKit)",
      what: "Un segundo programa independiente (SeqKit) resume el mismo archivo y sus resultados se comparan métrica por métrica con las estadísticas de ARVA.",
      why: "La coincidencia entre dos implementaciones independientes es una prueba sólida de que los números son correctos; una discrepancia señala un error o un caso límite que conviene investigar.",
      how: "Los recuentos y longitudes deben coincidir exactamente. La longitud media y los porcentajes solo admiten la diferencia causada por el redondeo de SeqKit. Los cuartiles no se comparan porque algunas versiones de SeqKit los calculan mal; el GC solo se compara si el archivo no tiene bases ambiguas.",
      interpret: "Si todas las métricas coinciden, las estadísticas de ARVA se reprodujeron de forma independiente. Cualquier fila «difiere» se muestra, nunca se oculta.",
      next: "Si una métrica difiere, anota ambas versiones y repórtalo; no te bases en esa métrica hasta resolverlo.",
      mistakes: ["Esperar decimales idénticos de herramientas que redondean distinto."],
      limitations: "Dos herramientas pueden compartir la misma interpretación errónea de un archivo mal formado; la validación de ARVA protege contra eso por separado.",
    },
  },
  {
    id: "fastqc_flags",
    references: [REF.fastqcHome, REF.fastqc],
    en: {
      title: "FastQC report and its PASS/WARN/FAIL flags",
      what: "FastQC runs a set of modules (per-base quality, sequence content, duplication, adapter content…) and marks each PASS, WARN or FAIL.",
      why: "It is the most widely used QC report and a common reference point between labs and in publications.",
      how: "ARVA runs FastQC unchanged, stores its HTML and ZIP outputs and shows the module flags. The original report can be opened inside ARVA (with network access blocked) or downloaded.",
      interpret: "The flags are FastQC's own heuristics, designed for diverse whole-genome shotgun libraries. A WARN or FAIL is a prompt to look at that module, not a verdict on your data; for example, amplicon or long-read data routinely 'fail' some modules.",
      next: "Open the module that is flagged and decide whether the pattern is expected for your library type.",
      mistakes: ["Discarding a dataset because of FAIL flags alone.", "Treating PASS as proof that the data are suitable for every analysis."],
      limitations: "FastQC is designed for short reads; on long reads some modules are slow or not meaningful.",
    },
    es: {
      title: "Informe FastQC y sus indicadores PASS/WARN/FAIL",
      what: "FastQC ejecuta una serie de módulos (calidad por base, composición, duplicación, contenido de adaptadores…) y marca cada uno como PASS, WARN o FAIL.",
      why: "Es el informe de QC más usado y un punto de referencia común entre laboratorios y en publicaciones.",
      how: "ARVA ejecuta FastQC sin modificarlo, guarda sus salidas HTML y ZIP y muestra los indicadores de cada módulo. El informe original puede abrirse dentro de ARVA (sin acceso a la red) o descargarse.",
      interpret: "Los indicadores son heurísticas propias de FastQC, pensadas para librerías diversas de secuenciación del genoma completo. Un WARN o FAIL invita a revisar ese módulo, no es un veredicto sobre tus datos; por ejemplo, los amplicones o las lecturas largas suelen «fallar» algunos módulos.",
      next: "Abre el módulo marcado y decide si el patrón es esperable para tu tipo de librería.",
      mistakes: ["Descartar un conjunto de datos solo por indicadores FAIL.", "Tomar PASS como prueba de que los datos sirven para cualquier análisis."],
      limitations: "FastQC está diseñado para lecturas cortas; con lecturas largas algunos módulos son lentos o poco significativos.",
    },
  },
  {
    id: "before_after",
    references: [REF.nanopack, REF.fastp],
    en: {
      title: "Before/after comparison",
      what: "Side-by-side statistics of an original file and the file derived from it by filtering, computed with exactly the same ARVA method.",
      why: "It shows precisely what a filter removed, so the decision to use filtered data is informed and documented.",
      how: "When a filtering job finishes, ARVA automatically computes read statistics for the new file (and for the original if missing). The table shows both values, the difference and the percentage retained; the charts overlay the two distributions on the same axes.",
      interpret: "Expect fewer reads and bases, and usually higher mean quality and length. Check that the bases retained are still enough for your planned depth.",
      next: "Proceed with the filtered file, adjust thresholds and run again (the earlier result is kept), or continue with the original.",
      mistakes: ["Judging a filter only by the increase in mean quality while ignoring how much data was lost."],
      limitations: "Statistics describe the reads, not whether the removed reads carried biologically important sequence (e.g. plasmids with unusual coverage).",
    },
    es: {
      title: "Comparación antes/después",
      what: "Estadísticas lado a lado de un archivo original y del archivo derivado tras el filtrado, calculadas exactamente con el mismo método de ARVA.",
      why: "Muestra con precisión qué eliminó un filtro, para que la decisión de usar datos filtrados quede informada y documentada.",
      how: "Cuando termina un filtrado, ARVA calcula automáticamente las estadísticas del archivo nuevo (y del original si faltan). La tabla muestra ambos valores, la diferencia y el porcentaje conservado; los gráficos superponen ambas distribuciones en los mismos ejes.",
      interpret: "Es esperable tener menos lecturas y bases, y normalmente mayor calidad y longitud media. Comprueba que las bases conservadas siguen siendo suficientes para la profundidad prevista.",
      next: "Continúa con el archivo filtrado, ajusta los umbrales y vuelve a ejecutar (el resultado anterior se conserva) o sigue con el original.",
      mistakes: ["Valorar un filtro solo por la mejora de calidad media ignorando cuántos datos se perdieron."],
      limitations: "Las estadísticas describen las lecturas, no si las eliminadas contenían secuencias biológicamente importantes (p. ej., plásmidos con cobertura inusual).",
    },
  },
];

export const GUIDE_BY_ID = Object.fromEntries(GUIDE.map((g) => [g.id, g])) as Record<GuideId, GuideEntry>;

export function localized(entry: GuideEntry, language: Language): Localized {
  return entry[language] ?? entry.en;
}
