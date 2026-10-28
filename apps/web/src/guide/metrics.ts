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
  | "before_after"
  | "read_headers"
  | "pod5"
  | "metadata_import"
  | "multiqc"
  | "nanoplot"
  | "qc_overview";

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
  multiqc: { label: "Ewels et al. (2016) Bioinformatics 32:3047–3048 — MultiQC", url: "https://doi.org/10.1093/bioinformatics/btw354" },
  multiqcHome: { label: "MultiQC project page and documentation", url: "https://multiqc.info" },
  nanopack2: {
    label: "De Coster & Rademakers (2023) Bioinformatics 39:btad311 — NanoPack2",
    url: "https://doi.org/10.1093/bioinformatics/btad311",
  },
  nanoplotHome: { label: "NanoPlot source code and documentation (W. De Coster)", url: "https://github.com/wdecoster/NanoPlot" },
  fastqcHome: { label: "FastQC project page and documentation (Babraham Bioinformatics)", url: "https://www.bioinformatics.babraham.ac.uk/projects/fastqc/" },
  illuminaFastq: { label: "Illumina BaseSpace Help — FASTQ files (sequence identifier fields)", url: "https://help.basespace.illumina.com/files-used-by-basespace/fastq-files" },
  bcl2fastq: {
    label: "Illumina bcl2fastq2 Conversion Software v2.20 Guide (15051736 v03), Table 7 — sequence identifier fields",
    url: "https://support.illumina.com/content/dam/illumina-support/documents/documentation/software_documentation/bcl2fastq/bcl2fastq2-v2-20-software-guide-15051736-03.pdf",
  },
  ontFastq: { label: "Oxford Nanopore output specifications — FASTQ read format", url: "https://software-docs.nanoporetech.com/output-specifications/latest/read_formats/fastq/" },
  doradoSam: { label: "Oxford Nanopore Dorado documentation — SAM specification", url: "https://software-docs.nanoporetech.com/dorado/latest/basecaller/sam_spec/" },
  pacbioBam: { label: "PacBio BAM format specification 13.1 — QNAME convention", url: "https://pacbiofileformats.readthedocs.io/en/13.1/BAM.html" },
  sraReadNames: { label: "NCBI sra-tools wiki — Read names (opaque identifiers, often replaced)", url: "https://github.com/ncbi/sra-tools/wiki/Read-Names" },
  elementOutputs: { label: "Element Biosciences bases2fastq — output files", url: "https://docs.elembio.io/docs/bases2fastq/outputs/" },
  pod5Spec: {
    label: "Oxford Nanopore Technologies — POD5 file format specification (pod5-file-format 0.3.49)",
    url: "https://raw.githubusercontent.com/nanoporetech/pod5-file-format/0.3.49/docs/SPECIFICATION.md",
  },
  pod5Docs: { label: "Oxford Nanopore POD5 documentation (pod5 Python library and tools)", url: "https://software-docs.nanoporetech.com/pod5/latest/" },
  dorado: { label: "Oxford Nanopore Dorado documentation (basecaller)", url: "https://software-docs.nanoporetech.com/dorado/latest/" },
  openpyxl: { label: "Gazoni E, Clark C — openpyxl 3.1 documentation (read-only mode, dates)", url: "https://openpyxl.readthedocs.io/en/stable/" },
  pythonCsv: { label: "Python Software Foundation — csv: CSV File Reading and Writing", url: "https://docs.python.org/3/library/csv.html" },
  owaspCsv: { label: "OWASP Foundation — CSV Injection", url: "https://owasp.org/www-community/attacks/CSV_Injection" },
  iso8601: { label: "ISO 8601 — Date and time format", url: "https://www.iso.org/iso-8601-date-and-time-format.html" },
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
      advanced: "mean_Q(read) = −10·log10( (1/L)·Σ 10^(−Qi/10) ). 'Mean read quality' is the arithmetic mean of these per-read values; NanoPlot's dataset 'Mean read quality' averages them again in error-probability space, so it is never higher. 'Mean base quality' applies the per-read formula over all bases in the file. Median read quality is reported at 0.1 Q resolution.",
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
      advanced: "mean_Q(lectura) = −10·log10( (1/L)·Σ 10^(−Qi/10) ). La 'calidad media de lectura' es la media aritmética de esos valores por lectura; la 'Mean read quality' de NanoPlot los vuelve a promediar en el espacio de probabilidades de error, por lo que nunca es mayor. La 'calidad media por base' aplica la fórmula por lectura a todas las bases. La mediana se reporta con resolución de 0,1 Q.",
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
  {
    id: "read_headers",
    references: [REF.illuminaFastq, REF.bcl2fastq, REF.ontFastq, REF.doradoSam, REF.pacbioBam, REF.sraReadNames, REF.elementOutputs, REF.fastq],
    en: {
      title: "Read headers and the platform hint",
      what: "The first line of every FASTQ record (the '>' line in FASTA) is a free-text read name. Sequencers and basecallers often write metadata into it: Illumina writes instrument, run, flow cell, lane and index; Oxford Nanopore's MinKNOW and Dorado write run ID, flow cell, basecalling model and barcode; PacBio writes the movie name and ZMW hole number.",
      why: "These values let you check that files come from the run you expect, that R1 and R2 belong together and which technology produced the reads, without any extra files.",
      how: "At import ARVA reads the header lines of the first 1,000 records (the records it validates anyway) and matches each one against documented grammars: Illumina CASAVA 1.8+ / bcl2fastq / BCL Convert, older Illumina names, ONT MinKNOW key=value attributes and Dorado SAM tags, PacBio read names and NCBI SRA deflines. Each header gets a platform hint with a confidence; a file's suggestion is 'high' only if no header disagrees and at least 90 % are high-confidence matches. For R1/R2 files, the read names without /1 or /2 of the first 200 records are compared position by position.",
      interpret: "The suggestion is evidence, not a fact. 'High' means a complete documented grammar matched (for Dorado headers, a single RG read-group tag that starts with a run ID is enough); 'low' means a single weak cue, such as a read ID that is a UUID. 'Not inferable' means the headers carry no platform information, which is common after renaming, simulation or download from NCBI SRA; it says nothing about which platform was used. ARVA never changes the sample's technology by itself.",
      next: "If the sample's technology is not set and the suggestion has medium or high confidence with evidence in every file, you can adopt it with 'Use this'; weaker suggestions are shown as hints only. If it disagrees with your records, check the run sheet, because tools can rewrite headers. If the R1/R2 check fails, confirm that the two files really are mates before paired-end filtering.",
      mistakes: [
        "Taking missing platform information as proof that a file is not Illumina, Nanopore or PacBio data: absence of evidence is not evidence.",
        "Reading Illumina read number 1 as proof of paired-end data: it also marks single-end reads.",
        "Treating a UUID read ID alone as proof of Nanopore data: UUIDs are not exclusive to ONT.",
      ],
      limitations: "Read names are opaque identifiers that tools may rewrite; NCBI SRA replaces most of them with serial numbers. Element Biosciences AVITI headers use an Illumina-compatible layout and are recognised only when the instrument name ends in _AVITI. Only the first records of each file are examined: up to 1,000, fewer when headers are very long (for example Dorado move tables).",
      advanced: "Illumina: @<instrument>:<run>:<flowcell>:<lane>:<tile>:<x>:<y>[:<UMI>] <read>:<Y|N>:<control>:<index | sample number>. ONT MinKNOW: @<uuid> key=value … (runid, ch, start_time, flow_cell_id, protocol_group_id, sample_id, barcode, basecall_model_version_id …). Dorado FASTQ: tab-separated SAM tags (RG:Z:<runid>_<model>[_<barcodes>], st, ch, PU, DT, SM, DS …); an RG:Z value starting with a UUID or 40-hex run ID and '_' alone gives high confidence, and the model part is not validated. PacBio: {movie}/{hole}/ccs[/fwd|rev][/{qStart}_{qEnd}] or {movie}/{hole}/{qStart}_{qEnd}. SRA: @<accession>.<spot> <spot name> length=<n> (fastq-dump --readids adds .1 or .2, which ARVA reads as the mate); platform cues kept inside an SRA defline are capped at medium confidence.",
    },
    es: {
      title: "Encabezados de lecturas e indicio de plataforma",
      what: "La primera línea de cada registro FASTQ (la línea '>' en FASTA) es un nombre de lectura de texto libre. Los secuenciadores y basecallers suelen escribir metadatos en él: Illumina escribe instrumento, corrida, celda de flujo, carril e índice; MinKNOW y Dorado de Oxford Nanopore escriben el ID de corrida, la celda de flujo, el modelo de basecalling y el código de barras; PacBio escribe el nombre de la movie y el número de pocillo ZMW.",
      why: "Estos valores permiten comprobar que los archivos vienen de la corrida esperada, que R1 y R2 van juntos y qué tecnología produjo las lecturas, sin archivos adicionales.",
      how: "Al importar, ARVA lee las líneas de encabezado de los primeros 1.000 registros (los mismos que valida) y compara cada una con gramáticas documentadas: Illumina CASAVA 1.8+ / bcl2fastq / BCL Convert, nombres Illumina antiguos, atributos clave=valor de ONT MinKNOW y etiquetas SAM de Dorado, nombres de lectura de PacBio y deflines de NCBI SRA. Cada encabezado recibe un indicio de plataforma con una confianza; la sugerencia de un archivo es «alta» solo si ningún encabezado discrepa y al menos el 90 % coincide con confianza alta. En archivos R1/R2 se comparan, posición por posición, los nombres de lectura sin /1 ni /2 de los primeros 200 registros.",
      interpret: "La sugerencia es una evidencia, no un hecho. «Alta» significa que coincidió una gramática documentada completa (en encabezados de Dorado basta una sola etiqueta de grupo de lectura RG que empiece por un ID de corrida); «baja», una sola pista débil, como un ID de lectura con forma de UUID. «No inferible» significa que los encabezados no contienen información de plataforma, algo habitual tras renombrar, simular o descargar de NCBI SRA; no dice nada sobre la plataforma usada. ARVA nunca cambia por su cuenta la tecnología de la muestra.",
      next: "Si la tecnología de la muestra no está indicada y la sugerencia tiene confianza media o alta con evidencia en todos los archivos, puedes adoptarla con «Usar esta»; las sugerencias más débiles solo se muestran como indicio. Si no coincide con tus registros, revisa la hoja de la corrida, porque las herramientas pueden reescribir los encabezados. Si falla la comprobación R1/R2, confirma que los dos archivos son realmente pareja antes de filtrar en modo paired-end.",
      mistakes: [
        "Tomar la falta de información de plataforma como prueba de que un archivo no es de Illumina, Nanopore o PacBio: la ausencia de evidencia no es evidencia.",
        "Interpretar el número de lectura 1 de Illumina como prueba de datos paired-end: también marca lecturas single-end.",
        "Tomar un ID de lectura UUID por sí solo como prueba de datos Nanopore: los UUID no son exclusivos de ONT.",
      ],
      limitations: "Los nombres de lectura son identificadores opacos que las herramientas pueden reescribir; NCBI SRA sustituye la mayoría por números de serie. Los encabezados de Element Biosciences AVITI usan una disposición compatible con Illumina y solo se reconocen cuando el nombre del instrumento termina en _AVITI. Solo se examinan los primeros registros de cada archivo: hasta 1.000, menos si los encabezados son muy largos (por ejemplo, con tablas de movimientos de Dorado).",
      advanced: "Illumina: @<instrumento>:<corrida>:<celda>:<carril>:<tile>:<x>:<y>[:<UMI>] <lectura>:<Y|N>:<control>:<índice | número de muestra>. ONT MinKNOW: @<uuid> clave=valor … (runid, ch, start_time, flow_cell_id, protocol_group_id, sample_id, barcode, basecall_model_version_id …). FASTQ de Dorado: etiquetas SAM separadas por tabuladores (RG:Z:<runid>_<modelo>[_<códigos>], st, ch, PU, DT, SM, DS …); un valor RG:Z que empieza por un UUID o un ID de corrida de 40 caracteres hexadecimales seguido de '_' da por sí solo confianza alta, y la parte del modelo no se valida. PacBio: {movie}/{pocillo}/ccs[/fwd|rev][/{qStart}_{qEnd}] o {movie}/{pocillo}/{qStart}_{qEnd}. SRA: @<accesión>.<spot> <nombre del spot> length=<n> (fastq-dump --readids añade .1 o .2, que ARVA interpreta como la pareja); las pistas de plataforma conservadas dentro de un defline SRA tienen como máximo confianza media.",
    },
  },
  {
    id: "pod5",
    references: [REF.pod5Spec, REF.pod5Docs, REF.dorado],
    en: {
      title: "POD5 raw-signal files",
      what: "POD5 is Oxford Nanopore's file format for raw signal: the electrical current measured while each DNA molecule passes through a pore, as recorded by MinKNOW. It also stores the run information (flow cell, sequencing kit, protocol, sample rate, software). It contains no bases and no quality scores; those are produced later by a basecaller such as Dorado.",
      why: "The run information documents where the data come from, and the signal is what you need to basecall again later with a newer model. Keeping the POD5 next to the FASTQ preserves that provenance.",
      how: "At import ARVA recognises POD5 by content, not by name: the first eight bytes must be the POD5 signature (8B 50 4F 44 0D 0A 1A 0A), and the file counts as complete only if the last eight bytes repeat it, as the specification describes. 'Read run metadata' opens the file with Oxford Nanopore's pod5 library and reads the run-information table and, for each read, only its sample count, acquisition and channel; the signal itself is never decoded. Signal duration is the sum over acquisitions of their samples divided by their sample rate.",
      interpret: "A 'read' in POD5 is one stretch of signal from one channel. Basecalling can split reads or discard some, so the number of FASTQ reads can differ. Signal duration adds up the time of all channels that recorded at the same time, so it is much longer than the run's wall-clock duration. Experiment and sample ID were typed into MinKNOW and are shown as written.",
      next: "Basecall the POD5 outside ARVA with Dorado (or let MinKNOW basecall during the run), then import the FASTQ to compute read statistics, run QC tools and filter reads. Note the basecalling model with the sample, because it changes read accuracy.",
      mistakes: [
        "Reading the signal duration as the length of the run: it is summed over all channels.",
        "Expecting the POD5 read count to equal the FASTQ read count after basecalling.",
        "Trying to repair a truncated POD5 with 'pod5 recover': it only works with MinKNOW's temporary files. Copy the file again from its source instead.",
      ],
      limitations: "ARVA reads POD5 metadata only; it does not basecall. The reader was validated with synthetic POD5 files written by the pod5 library, not with files from every MinKNOW version. POD5 bytes are not reproducible (every file gets a random identifier), so compare files by their content, not by the checksum of a regenerated file. Fields that can identify people, computers or devices (system name, sequencer position, context tags, tracking ID) are kept only in the job's JSON output.",
      advanced: "Layout: <signature> <16-byte section marker> <embedded Arrow IPC tables: signal, run information, reads> <footer> <footer length> <section marker> <signature>. ARVA records the file attributes reported by pod5.Reader (writing software, file identifier, file version before and after migration, VBZ compression, batch count), the run-information table and the read-table columns num_samples, run_info (the dictionary-encoded acquisition ID) and channel_32bit. pod5 0.3.49 has no wheel for Intel Macs; bioconda's lib-pod5 / pod5 0.3.49 packages provide it there.",
    },
    es: {
      title: "Archivos de señal cruda POD5",
      what: "POD5 es el formato de Oxford Nanopore para la señal cruda: la corriente eléctrica medida mientras cada molécula de ADN atraviesa un poro, tal como la registra MinKNOW. También guarda la información de la corrida (celda de flujo, kit de secuenciación, protocolo, frecuencia de muestreo, software). No contiene bases ni calidades; esas las produce después un basecaller como Dorado.",
      why: "La información de la corrida documenta el origen de los datos, y la señal es lo que se necesita para repetir el basecalling más adelante con un modelo más nuevo. Conservar el POD5 junto al FASTQ preserva esa trazabilidad.",
      how: "Al importar, ARVA reconoce POD5 por el contenido, no por el nombre: los primeros ocho bytes deben ser la firma POD5 (8B 50 4F 44 0D 0A 1A 0A), y el archivo se considera completo solo si los últimos ocho bytes la repiten, como describe la especificación. «Leer metadatos de corrida» abre el archivo con la biblioteca pod5 de Oxford Nanopore y lee la tabla de información de la corrida y, de cada lectura, solo su número de muestras, su adquisición y su canal; la señal nunca se decodifica. La duración de la señal es la suma, por adquisición, de sus muestras divididas por su frecuencia de muestreo.",
      interpret: "Una «lectura» en POD5 es un tramo de señal de un canal. El basecalling puede dividir lecturas o descartar algunas, así que el número de lecturas del FASTQ puede ser distinto. La duración de la señal suma el tiempo de todos los canales que registraron a la vez, por lo que es mucho mayor que la duración real de la corrida. El experimento y el ID de muestra se escribieron en MinKNOW y se muestran tal cual.",
      next: "Haz el basecalling del POD5 fuera de ARVA con Dorado (o deja que MinKNOW lo haga durante la corrida) y luego importa el FASTQ para calcular estadísticas de lecturas, ejecutar herramientas de QC y filtrar. Anota el modelo de basecalling en la muestra, porque cambia la exactitud de las lecturas.",
      mistakes: [
        "Interpretar la duración de la señal como la duración de la corrida: está sumada sobre todos los canales.",
        "Esperar que el número de lecturas del POD5 coincida con el del FASTQ tras el basecalling.",
        "Intentar reparar un POD5 truncado con «pod5 recover»: solo funciona con los archivos temporales de MinKNOW. Copia de nuevo el archivo desde su origen.",
      ],
      limitations: "ARVA solo lee los metadatos de POD5; no hace basecalling. El lector se validó con archivos POD5 sintéticos escritos por la biblioteca pod5, no con archivos de todas las versiones de MinKNOW. Los bytes de un POD5 no son reproducibles (cada archivo recibe un identificador aleatorio), así que compara archivos por su contenido, no por la suma de verificación de un archivo regenerado. Los campos que pueden identificar a personas, ordenadores o dispositivos (nombre del sistema, posición del secuenciador, etiquetas de contexto, ID de seguimiento) solo se guardan en la salida JSON del trabajo.",
      advanced: "Estructura: <firma> <marcador de sección de 16 bytes> <tablas Arrow IPC incrustadas: señal, información de corrida, lecturas> <pie> <longitud del pie> <marcador de sección> <firma>. ARVA registra los atributos que informa pod5.Reader (software que escribió el archivo, identificador del archivo, versión del archivo antes y después de la migración, compresión VBZ, número de lotes), la tabla de información de la corrida y las columnas num_samples, run_info (el ID de adquisición codificado como diccionario) y channel_32bit de la tabla de lecturas. pod5 0.3.49 no tiene wheel para Mac con Intel; allí lo proporcionan los paquetes lib-pod5 / pod5 0.3.49 de bioconda.",
    },
  },
  {
    id: "metadata_import",
    references: [REF.openpyxl, REF.pythonCsv, REF.owaspCsv, REF.iso8601],
    en: {
      title: "Importing sample metadata from CSV or Excel",
      what: "A metadata table has one row per sample and one column per piece of information: sample ID, host, origin, collection date, sequencing technology and so on. ARVA reads CSV, TSV and TXT text tables and Excel .xlsx workbooks, and sends each column to a sample field, to the sample's custom metadata, or nowhere.",
      why: "Typing the metadata of a whole run sample by sample is slow and error-prone. Importing the spreadsheet you already keep, after a preview of every change, keeps ARVA consistent with your laboratory records.",
      how: "Text files are decoded as UTF-8 (with or without BOM) or UTF-16 with BOM, and otherwise as Windows-1252 with a warning. The delimiter (comma, semicolon, tab or |) is detected or chosen, and Excel's 'sep=' first line is honoured. Workbooks are read with openpyxl: every cell becomes text, native Excel dates become YYYY-MM-DD, formulas contribute only the value stored by the program that saved the file, merged cells are reported but never filled in, and error cells such as #N/A are imported as empty. Column names are matched exactly, ignoring case, accents, punctuation and text in brackets, against English and Spanish names: Sample ID / ID muestra / Código → sample ID; Host / Hospedador → host; Country / País / Origen → geographic origin; Date / Fecha de muestreo → collection date; Platform / Tecnología → sequencing technology; Organism / Organismo, Run / Corrida, Researcher / Investigador, Notes / Observaciones and others. Any other column becomes custom metadata. Existing samples are matched by exact sample ID, then by a single match that ignores letter case.",
      interpret: "The preview labels each row new, update, unchanged or error and lists every change as old → new. Only non-empty cells are written, so an empty cell never deletes a stored value. Technology values are mapped to Illumina, Oxford Nanopore, PacBio or hybrid from instrument names (MiSeq, NovaSeq, MinION, PromethION, Sequel, Revio, HiFi…); platforms ARVA has no value for, such as Ion Torrent, DNBSEQ or AVITI, are kept as text in the custom metadata. Dates are accepted only in explicit forms: YYYY-MM-DD (ISO 8601), a day/month order that the value itself proves (15/03/2024), month names (15 de marzo de 2024), or the order you choose for ambiguous dates such as 03/05/2024.",
      next: "Apply the import when the preview looks right. The project's import history keeps the file name, its SHA-256 checksum, how it was read and the column mapping. Export the metadata as CSV or Excel to share or archive it, or download the template to start a new table.",
      mistakes: [
        "Typing sample codes such as 001 into an Excel column formatted as numbers: Excel stores 1. Format the column as Text, as the ARVA template does.",
        "Expecting ARVA to guess whether 03/05/2024 is 3 May or 5 March: it never guesses.",
        "Uploading an old .xls workbook: save it as .xlsx or 'CSV UTF-8' first.",
        "Leaving a cell empty to delete a stored value: empty cells are ignored, so edit the sample instead (its Metadata tab, where custom fields can also be changed or removed).",
      ],
      limitations: "Old .xls, macro-enabled .xlsm, binary .xlsb and OpenDocument .ods files are not read: .xls is a legacy binary format that openpyxl cannot read, and macros are never run. Formulas are never calculated, so a workbook saved by a program that does not store formula results imports those cells as empty (ARVA warns). Partial dates such as '2024' or '2024-03' cannot be stored as a collection date and are kept as text in the custom metadata. Limits: 10 MiB per file, 10,000 rows, 256 columns and 10,000 characters per cell (configurable by the administrator).",
      advanced: "Exports are formula-injection safe. In CSV (UTF-8 with BOM, every field quoted), cells that start with =, +, -, @, tab, carriage return or line feed, or their full-width forms, get a leading apostrophe, as the OWASP guidance on CSV injection recommends, so spreadsheet programs show them as text instead of running them; plain numbers such as -34.6 are left untouched. When such a CSV is imported again, ARVA removes exactly that apostrophe and says so, so an export can be edited and re-imported without changing values. In .xlsx exports every cell is written as a text cell, so '=…' never becomes a formula. Before a workbook is opened, ARVA checks the zip container (at most 2,000 parts and 100 MiB uncompressed, no part above 1 MiB that expands more than 250 times, at most 250,000 distinct texts) and the size of the sheet, empty formatted cells included, to refuse zip bombs, and the XML parser refuses entity-expansion attacks.",
    },
    es: {
      title: "Importar metadatos de muestras desde CSV o Excel",
      what: "Una tabla de metadatos tiene una fila por muestra y una columna por dato: ID de muestra, hospedador, origen, fecha de muestreo, tecnología de secuenciación, etc. ARVA lee tablas de texto CSV, TSV y TXT y libros de Excel .xlsx, y envía cada columna a un campo de la muestra, a sus metadatos personalizados o a ningún sitio.",
      why: "Escribir los metadatos de una corrida completa muestra por muestra es lento y propenso a errores. Importar la hoja que ya mantienes, tras revisar cada cambio, mantiene ARVA coherente con los registros del laboratorio.",
      how: "Los archivos de texto se decodifican como UTF-8 (con o sin BOM) o UTF-16 con BOM, y si no, como Windows-1252 con una advertencia. El separador (coma, punto y coma, tabulador o |) se detecta o se elige, y se respeta la primera línea 'sep=' de Excel. Los libros se leen con openpyxl: cada celda se convierte en texto, las fechas nativas de Excel pasan a AAAA-MM-DD, las fórmulas aportan solo el valor guardado por el programa que guardó el archivo, las celdas combinadas se señalan pero nunca se rellenan y las celdas de error como #N/A se importan vacías. Los nombres de columna se comparan de forma exacta, sin distinguir mayúsculas, tildes, puntuación ni el texto entre paréntesis, con nombres en inglés y español: Sample ID / ID muestra / Código → ID de muestra; Host / Hospedador → hospedador; Country / País / Origen → origen geográfico; Date / Fecha de muestreo → fecha de muestreo; Platform / Tecnología → tecnología de secuenciación; Organism / Organismo, Run / Corrida, Researcher / Investigador, Notes / Observaciones y otros. Cualquier otra columna pasa a metadatos personalizados. Las muestras existentes se buscan por ID exacto y, si no, por una única coincidencia sin distinguir mayúsculas y minúsculas.",
      interpret: "La vista previa marca cada fila como nueva, actualizar, sin cambios o error y muestra cada cambio como anterior → nuevo. Solo se escriben las celdas con contenido, así que una celda vacía nunca borra un valor guardado. La tecnología se asigna a Illumina, Oxford Nanopore, PacBio o híbrida a partir de los nombres de instrumento (MiSeq, NovaSeq, MinION, PromethION, Sequel, Revio, HiFi…); las plataformas sin valor en ARVA, como Ion Torrent, DNBSEQ o AVITI, se guardan como texto en los metadatos personalizados. Las fechas solo se aceptan en formas explícitas: AAAA-MM-DD (ISO 8601), un orden día/mes que el propio valor demuestra (15/03/2024), nombres de mes (15 de marzo de 2024) o el orden que elijas para fechas ambiguas como 03/05/2024.",
      next: "Aplica la importación cuando la vista previa sea correcta. El historial de importaciones del proyecto guarda el nombre del archivo, su suma SHA-256, cómo se leyó y la asignación de columnas. Exporta los metadatos a CSV o Excel para compartirlos o archivarlos, o descarga la plantilla para empezar una tabla nueva.",
      mistakes: [
        "Escribir códigos como 001 en una columna de Excel con formato de número: Excel guarda 1. Da formato de Texto a la columna, como hace la plantilla de ARVA.",
        "Esperar que ARVA adivine si 03/05/2024 es 3 de mayo o 5 de marzo: nunca lo adivina.",
        "Subir un libro antiguo .xls: guárdalo antes como .xlsx o «CSV UTF-8».",
        "Dejar una celda vacía para borrar un valor guardado: las celdas vacías se ignoran, así que edita la muestra (en su pestaña Metadatos, donde también se pueden cambiar o quitar los campos personalizados).",
      ],
      limitations: "No se leen archivos antiguos .xls, .xlsm con macros, .xlsb binarios ni .ods de OpenDocument: .xls es un formato binario heredado que openpyxl no puede leer, y las macros nunca se ejecutan. Las fórmulas nunca se calculan, así que un libro guardado por un programa que no guarda sus resultados importa esas celdas vacías (ARVA lo advierte). Las fechas parciales como «2024» o «2024-03» no pueden guardarse como fecha de muestreo y se conservan como texto en los metadatos personalizados. Límites: 10 MiB por archivo, 10.000 filas, 256 columnas y 10.000 caracteres por celda (configurables por quien administra ARVA).",
      advanced: "Las exportaciones están protegidas contra la inyección de fórmulas. En CSV (UTF-8 con BOM, todos los campos entre comillas), las celdas que empiezan por =, +, -, @, tabulador, retorno de carro o salto de línea, o sus formas de ancho completo, llevan un apóstrofo inicial, como recomienda la guía de OWASP sobre inyección CSV, para que las hojas de cálculo las muestren como texto en lugar de ejecutarlas; los números simples como -34.6 no se modifican. Al volver a importar ese CSV, ARVA quita exactamente ese apóstrofo y lo indica, así que una exportación puede editarse y volver a importarse sin cambiar los valores. En las exportaciones .xlsx cada celda se escribe como celda de texto, así que «=…» nunca se convierte en fórmula. Antes de abrir un libro, ARVA comprueba el contenedor zip (como máximo 2.000 partes y 100 MiB sin comprimir, ninguna parte de más de 1 MiB que se expanda más de 250 veces, como máximo 250.000 textos distintos) y el tamaño de la hoja, incluidas las celdas vacías con formato, para rechazar bombas zip, y el analizador XML rechaza los ataques de expansión de entidades.",
    },
  },
  {
    id: "multiqc",
    references: [REF.multiqc, REF.multiqcHome, REF.fastqcHome, REF.fastp, REF.seqkit, REF.filtlong],
    en: {
      title: "Project QC report (MultiQC)",
      what: "MultiQC reads the output files of other QC tools (here FastQC, fastp, SeqKit and Filtlong) for the samples of a project and gathers them in one interactive HTML report: a general-statistics table and the tools' plots side by side.",
      why: "Comparing samples one report at a time is slow; side by side, a sample with fewer reads, lower quality or unusual GC stands out. A MultiQC report is also a common way to share the QC of a whole project.",
      how: "ARVA chooses the results: the most recent completed FastQC and SeqKit result of each file, and the most recent fastp and Filtlong result of each input (Filtlong only when it ran with a target), only for files ARVA has read in full with its own read statistics and found valid. It copies those files into the job folder under neutral names and gives MultiQC that exact list (--file-list), never a folder to search. Samples are named '<sample ID> <file>' through an exact renaming table; when two samples or files would get the same name (MultiQC would merge their rows), the first 8 characters of their ARVA IDs are added. MultiQC 1.35 runs offline, with its version check, AI features and uploads switched off, in an empty folder with an empty home folder. Afterwards ARVA checks that every file appears in the report exactly once, because MultiQC finishes without an error even when it skips a file, and it reads the raw general-statistics values from multiqc_data.json together with the unit of each value.",
      interpret: "Every number was computed by the tool that wrote the file, except a few percentages MultiQC derives from them (for example fastp's % passing filter, % adapter and % duplication), which ARVA marks as computed by MultiQC. Read each column with its tool's definition: FastQC's GC is a whole-number percentage of all bases, SeqKit's has two decimals, and fastp's is a fraction after filtering. Such columns are not the same measurement and ARVA does not compare them. FastQC's PASS/WARN/FAIL marks remain FastQC's heuristics.",
      next: "Open the report to compare samples, then open a sample in ARVA for its own statistics and each tool's full report. Build the report again after new QC runs; earlier reports are kept together with their inputs.",
      mistakes: [
        "Treating MultiQC as an independent check: it shows the same tool outputs again.",
        "Comparing metrics with similar names from different tools as if they were one measurement.",
        "Sharing the HTML file without noticing that it contains sample IDs and file names.",
      ],
      limitations: "Only FastQC, fastp, SeqKit and Filtlong results are included, and Filtlong runs without a target are left out because their log has no totals MultiQC can read. The report embeds sample IDs and file names and is meant for viewing on this computer; ARVA serves it isolated from ARVA and with network access blocked, so links in it to external documentation do not load inside ARVA and settings changed inside the report are not kept. The data files contain local folder paths. Column names change between MultiQC versions: ARVA reads only the columns it knows for MultiQC 1.35 and lists the others.",
      advanced: "Command (an argument list, no shell): multiqc --file-list inputs.txt --outdir <job> --filename arva_multiqc_report.html --force --no-version-check --no-ai --no-ansi --no-megaqc-upload --interactive --data-format tsv --title … --comment <job ID> --config arva_multiqc_config.yaml --fn_as_s_name --fullnames --replace-names sample_names.tsv --module … --require-logs, with MULTIQC_NO_VERSION_CHECK=true. The configuration sets no_version_check, no_ai, show_analysis_paths: false, unscaled counts (read_count_multiplier and base_count_multiplier 1), exact sample renaming, empty DOI lists (which remove badges that query api.crossref.org on hover) and a longer Filtlong search window, because Filtlong's progress lines otherwise hide the text MultiQC looks for. The page is served with Content-Security-Policy sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'. The sandbox gives it an origin of its own, so nothing in the report can reach ARVA's data; because MultiQC's scripts need localStorage, which a sandbox forbids, ARVA adds a small in-memory stand-in at the top of the page when serving it (the stored file is unchanged). Filtlong logs written with digit grouping (1,362,402, from runs in an en_US locale) are copied without the separators, since MultiQC cannot read them; Filtlong itself now runs with LC_ALL=C. Sample names and the title are reduced to letters, digits and a few punctuation marks because MultiQC does not escape them in its HTML. MultiQC is installed from PyPI (multiqc 1.35 with plotly 5.24.1) in its own Python environment; the Ubuntu/Debian 1.18 package is not used.",
    },
    es: {
      title: "Informe de QC del proyecto (MultiQC)",
      what: "MultiQC lee los archivos de salida de otras herramientas de QC (aquí FastQC, fastp, SeqKit y Filtlong) de las muestras de un proyecto y los reúne en un único informe HTML interactivo: una tabla de estadísticas generales y los gráficos de las herramientas lado a lado.",
      why: "Comparar muestras informe por informe es lento; lado a lado, una muestra con menos lecturas, menor calidad o un GC inusual destaca enseguida. Un informe de MultiQC es además una forma habitual de compartir el QC de todo un proyecto.",
      how: "ARVA elige los resultados: el resultado completado más reciente de FastQC y de SeqKit de cada archivo, y el más reciente de fastp y de Filtlong de cada entrada (Filtlong solo si se ejecutó con un objetivo), solo de archivos que ARVA ha leído completos con sus propias estadísticas de lectura y considerado válidos. Copia esos archivos en la carpeta del trabajo con nombres neutros y entrega a MultiQC esa lista exacta (--file-list), nunca una carpeta para buscar. Las muestras se llaman «<ID de muestra> <archivo>» mediante una tabla de renombrado exacto; cuando dos muestras o archivos recibirían el mismo nombre (MultiQC uniría sus filas), se añaden los 8 primeros caracteres de sus ID de ARVA. MultiQC 1.35 se ejecuta sin conexión, con la comprobación de versión, las funciones de IA y las subidas desactivadas, en una carpeta vacía y con una carpeta personal vacía. Después ARVA comprueba que cada archivo aparece exactamente una vez en el informe, porque MultiQC termina sin error aunque omita un archivo, y lee de multiqc_data.json los valores sin transformar de las estadísticas generales junto con la unidad de cada valor.",
      interpret: "Cada número lo calculó la herramienta que escribió el archivo, salvo algunos porcentajes que MultiQC deriva de ellos (por ejemplo, el % que pasa los filtros, el % con adaptador y el % de duplicación de fastp), que ARVA marca como calculados por MultiQC. Lee cada columna con la definición de su herramienta: el GC de FastQC es un porcentaje entero de todas las bases, el de SeqKit tiene dos decimales y el de fastp es una fracción tras el filtrado. No son la misma medida y ARVA no las compara. Las marcas PASS/WARN/FAIL de FastQC siguen siendo heurísticas de FastQC.",
      next: "Abre el informe para comparar muestras y después abre una muestra en ARVA para ver sus propias estadísticas y el informe completo de cada herramienta. Vuelve a generar el informe tras nuevos análisis de QC; los informes anteriores se conservan junto con sus entradas.",
      mistakes: [
        "Tomar MultiQC como una verificación independiente: vuelve a mostrar las mismas salidas de las herramientas.",
        "Comparar métricas de nombre parecido de herramientas distintas como si fueran una misma medida.",
        "Compartir el archivo HTML sin advertir que contiene IDs de muestra y nombres de archivo.",
      ],
      limitations: "Solo se incluyen resultados de FastQC, fastp, SeqKit y Filtlong, y se dejan fuera las ejecuciones de Filtlong sin objetivo porque su registro no tiene totales que MultiQC pueda leer. El informe incluye IDs de muestra y nombres de archivo y está pensado para verse en este ordenador; ARVA lo sirve aislado de ARVA y con el acceso a la red bloqueado, así que sus enlaces a documentación externa no se cargan dentro de ARVA y los ajustes cambiados dentro del informe no se guardan. Los archivos de datos contienen rutas de carpetas locales. Los nombres de las columnas cambian entre versiones de MultiQC: ARVA solo lee las columnas que conoce para MultiQC 1.35 y enumera las demás.",
      advanced: "Comando (una lista de argumentos, sin shell): multiqc --file-list inputs.txt --outdir <trabajo> --filename arva_multiqc_report.html --force --no-version-check --no-ai --no-ansi --no-megaqc-upload --interactive --data-format tsv --title … --comment <ID del trabajo> --config arva_multiqc_config.yaml --fn_as_s_name --fullnames --replace-names sample_names.tsv --module … --require-logs, con MULTIQC_NO_VERSION_CHECK=true. La configuración fija no_version_check, no_ai, show_analysis_paths: false, recuentos sin escalar (read_count_multiplier y base_count_multiplier 1), renombrado exacto de muestras, listas de DOI vacías (que eliminan las insignias que consultan api.crossref.org al pasar el ratón) y una ventana de búsqueda más larga para Filtlong, porque sus líneas de progreso ocultan si no el texto que busca MultiQC. La página se sirve con Content-Security-Policy sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'. El sandbox le da un origen propio, así que nada del informe puede llegar a los datos de ARVA; como los scripts de MultiQC necesitan localStorage, que un sandbox prohíbe, ARVA añade al servirla un pequeño sustituto en memoria al principio de la página (el archivo guardado no cambia). Los registros de Filtlong escritos con separadores de miles (1,362,402, de ejecuciones con configuración regional en_US) se copian sin los separadores, porque MultiQC no puede leerlos; Filtlong se ejecuta ahora con LC_ALL=C. Los nombres de muestra y el título se reducen a letras, dígitos y algunos signos de puntuación porque MultiQC no los escapa en su HTML. MultiQC se instala desde PyPI (multiqc 1.35 con plotly 5.24.1) en su propio entorno de Python; no se usa el paquete 1.18 de Ubuntu/Debian.",
    },
  },
  {
    id: "nanoplot",
    references: [REF.nanopack2, REF.nanopack, REF.nanoplotHome, REF.phred],
    en: {
      title: "NanoPlot report (long reads)",
      what: "NanoPlot, part of the NanoPack tools, summarises long reads (Oxford Nanopore, PacBio): number of reads and bases, read length and quality statistics, and an interactive HTML report with length histograms, yield by read length and read length against quality.",
      why: "It is a widely used, independent summary of long-read data, and its report is a familiar way to share the QC of a run. Next to ARVA's own statistics it also confirms the basic counts of the file.",
      how: "ARVA runs NanoPlot 1.48.0 on one FASTQ file at a time, offline, in an empty working folder with an empty home folder: --no_static (without it NanoPlot downloads and starts a web browser to draw PNG images), --only-report, --include-js embedded (the plotting library inside the report, so it opens without internet) and --tsv_stats. Afterwards ARVA checks that NanoStats.txt, the report and NanoPlot's log exist, because NanoPlot can write NanoStats.txt and then stop with an error, and that no browser files appeared in the home folder. ARVA reads NanoStats.txt by row name and keeps each value with NanoPlot's definition.",
      interpret: "Reads and total bases mean the same in NanoPlot and ARVA, so ARVA checks them against each other; nanoget skips zero-length records, which ARVA counts, so a read count lower by exactly that number is explained, not an error. Other values share names but not definitions: NanoPlot's N50 sorts lengths from shortest to longest (lengths 2, 3 and 5 give 3; ARVA and SeqKit give 5), its 'Reads >Q10' counts reads strictly above Q10 where ARVA counts at or above, and its mean read quality averages per-read qualities again as error probabilities, while ARVA's is their arithmetic mean. These are shown side by side or separately and never judged equal or different.",
      next: "Open the report for NanoPlot's interactive plots. To remove short or low-quality reads, use Filtlong in the Filtering tab; NanoPlot changes no data.",
      mistakes: [
        "Reading NanoPlot's mean read quality as ARVA's mean read quality: they are different averages of the same per-read values.",
        "Taking equal N50 values from ARVA and NanoPlot as a check: the two definitions can disagree on the same reads.",
        "Running NanoPlot on short reads: its plots and statistics are designed for long reads.",
      ],
      limitations: "Only plain FASTQ files are read (no BAM, sequencing_summary.txt or POD5), so the channel and time plots for MinKNOW data are not available. The plots are drawn from random subsets of at most 10,000 reads (2,000 for the density plot) chosen without a fixed seed, so for larger files they are not exactly reproducible; the statistics use every read. NanoPlot removes reads shorter than 20 bases with a mean quality above 30 as basecaller artefacts after writing NanoStats.txt and describes the rest in NanoStats_post_filtering.txt. Its log file lists local folder paths.",
      advanced: "Command (an argument list, no shell): NanoPlot --fastq <file> --outdir <job> --prefix <name>_ --threads <n> --no_static --only-report --include-js embedded --tsv_stats. The input is a link named after the file with a .fastq or .fastq.gz extension, because nanoget chooses its reader from the extension alone. --downsample (no seed) and --info_in_report (writes folder paths into the report) are never used. The report is served with ARVA's sandboxed Content-Security-Policy (default-src 'none'); in headless Chromium all plots render with it and no request leaves the page. NanoPlot is installed from PyPI (NanoPlot 1.48.0 with nanoget 1.19.6) in its own Python environment: the package also installs modules with generic names and carries its own modified copy of nanomath, which installing nanomath separately would replace and change the mean quality; when it detects NanoPlot, ARVA imports nanomath with NanoPlot's own Python and does not run NanoPlot if that copy has been replaced.",
    },
    es: {
      title: "Informe de NanoPlot (lecturas largas)",
      what: "NanoPlot, parte de las herramientas NanoPack, resume lecturas largas (Oxford Nanopore, PacBio): número de lecturas y de bases, estadísticas de longitud y de calidad, y un informe HTML interactivo con histogramas de longitud, rendimiento por longitud de lectura y longitud frente a calidad.",
      why: "Es un resumen independiente y muy usado de datos de lecturas largas, y su informe es una forma conocida de compartir el QC de una carrera. Junto a las estadísticas de ARVA también confirma los recuentos básicos del archivo.",
      how: "ARVA ejecuta NanoPlot 1.48.0 sobre un archivo FASTQ cada vez, sin conexión, en una carpeta de trabajo vacía y con una carpeta personal vacía: --no_static (sin ella NanoPlot descarga e inicia un navegador web para dibujar imágenes PNG), --only-report, --include-js embedded (la biblioteca de gráficos dentro del informe, que así se abre sin internet) y --tsv_stats. Después ARVA comprueba que existen NanoStats.txt, el informe y el registro de NanoPlot, porque NanoPlot puede escribir NanoStats.txt y detenerse luego con un error, y que no apareció ningún archivo de navegador en la carpeta personal. ARVA lee NanoStats.txt por nombre de fila y guarda cada valor con la definición de NanoPlot.",
      interpret: "Las lecturas y las bases totales significan lo mismo en NanoPlot y en ARVA, así que ARVA las compara; nanoget omite los registros de longitud cero, que ARVA sí cuenta, de modo que un número de lecturas menor exactamente en esa cantidad está explicado y no es un error. Otros valores comparten nombre pero no definición: el N50 de NanoPlot ordena las longitudes de la más corta a la más larga (longitudes 2, 3 y 5 dan 3; ARVA y SeqKit dan 5), su 'Reads >Q10' cuenta lecturas estrictamente por encima de Q10 mientras ARVA cuenta las iguales o superiores, y su calidad media de lectura vuelve a promediar las calidades por lectura como probabilidades de error, mientras que la de ARVA es su media aritmética. Se muestran lado a lado o por separado y nunca se juzgan iguales o distintos.",
      next: "Abre el informe para ver los gráficos interactivos de NanoPlot. Para eliminar lecturas cortas o de baja calidad usa Filtlong en la pestaña Filtrado; NanoPlot no modifica datos.",
      mistakes: [
        "Leer la calidad media de NanoPlot como la calidad media de lectura de ARVA: son promedios distintos de los mismos valores por lectura.",
        "Tomar como comprobación que ARVA y NanoPlot den el mismo N50: las dos definiciones pueden discrepar con las mismas lecturas.",
        "Ejecutar NanoPlot sobre lecturas cortas: sus gráficos y estadísticas están pensados para lecturas largas.",
      ],
      limitations: "Solo se leen archivos FASTQ simples (no BAM, sequencing_summary.txt ni POD5), así que no hay gráficos de canales ni de tiempo para datos de MinKNOW. Los gráficos se dibujan con subconjuntos aleatorios de como máximo 10 000 lecturas (2000 para el gráfico de densidad) elegidos sin semilla fija, así que en archivos más grandes no son exactamente reproducibles; las estadísticas usan todas las lecturas. NanoPlot elimina como artefactos del basecalling las lecturas de menos de 20 bases con calidad media superior a 30 después de escribir NanoStats.txt y describe el resto en NanoStats_post_filtering.txt. Su archivo de registro indica rutas de carpetas locales.",
      advanced: "Comando (una lista de argumentos, sin shell): NanoPlot --fastq <archivo> --outdir <trabajo> --prefix <nombre>_ --threads <n> --no_static --only-report --include-js embedded --tsv_stats. La entrada es un enlace con el nombre del archivo y la extensión .fastq o .fastq.gz, porque nanoget elige cómo leerlo solo por la extensión. Nunca se usan --downsample (sin semilla) ni --info_in_report (escribe rutas de carpetas en el informe). El informe se sirve con la Content-Security-Policy aislada de ARVA (default-src 'none'); en Chromium sin interfaz todos los gráficos se dibujan con ella y ninguna petición sale de la página. NanoPlot se instala desde PyPI (NanoPlot 1.48.0 con nanoget 1.19.6) en su propio entorno de Python: el paquete instala también módulos de nombre genérico y lleva su propia copia modificada de nanomath, que se sustituiría al instalar nanomath por separado y cambiaría la calidad media; al detectar NanoPlot, ARVA importa nanomath con el Python del propio NanoPlot y no lo ejecuta si esa copia ha sido sustituida.",
    },
  },
  {
    id: "qc_overview",
    references: [REF.quast, REF.phred, REF.lander, REF.fastqc, REF.seqkit, REF.owaspCsv],
    en: {
      title: "Sequencing overview and project QC overview",
      what: "Two summary tables. On a sample's QC tab, the sequencing overview lists every file of the sample, imported and derived (filtered), with reads, bases, mean length, N50, mean read quality, bases ≥ Q30 and GC, and for POD5 raw-signal files the reads and signal duration; a bar chart shows the bases of each file. On the project page, the QC overview has one row per sample with the headline values, the filtering done, FastQC's flags and the SeqKit cross-check.",
      why: "They let you see at a glance which files and samples have been analysed, how much data each holds and where something needs a closer look, before opening each sample. The project table can be sorted, filtered by technology and downloaded as CSV.",
      how: "Only completed analyses give values, always the latest completed one of each file; anything else is shown as — with the reason (not computed, being computed, failed). Per file, the values are ARVA's own read statistics; POD5 values come from the pod5 library. Per sample, ARVA uses the imported read files (FASTQ/FASTA): reads and bases are their sums; N50 and mean read quality are those of the imported read file with the most bases (on a tie, the one imported first), because N50 and a mean of per-read qualities cannot be combined across files; bases ≥ Q30 and GC are pooled exactly over the files (Q30 over all bases of the FASTQ files, GC over all unambiguous bases). These values are shown only when every imported read file has statistics, so a sum is never silently partial. Depth = total bases ÷ the expected genome size you entered when computing the statistics, only if the same size was entered for every imported read file; ARVA never assumes a genome size. Filtering shows the latest completed fastp or Filtlong run and the share of reads and bases kept, from ARVA's statistics of its output and input files. FastQC flags are summed over the latest report of each imported FASTQ file. The SeqKit check compares SeqKit with ARVA on each imported read file: 'agrees' when every file was checked and all agree, 'agrees (n of m files)' when only some files were checked and those agree, 'differs' when at least one metric of at least one checked file differs (even if other files agree), and 'not run' when no file was checked.",
      interpret: "Compare samples of the same technology with each other: the table filter helps. Large differences in yield, N50 or quality between samples of one run often point to library or loading problems worth checking on the sample page. FastQC flags are FastQC's heuristics for short-read whole-genome libraries, not verdicts; a 'differs' in the SeqKit column means a number should not be relied on until explained.",
      next: "Open a sample from the table for its per-file statistics, charts and reports. Download the CSV to keep the overview with your records; it is protected against spreadsheet formula injection.",
      mistakes: [
        "Reading the N50 of the overview as an N50 of all reads of the sample: it is the N50 of the largest imported file.",
        "Taking the estimated depth as measured coverage: it assumes that every base comes from the target genome.",
        "Treating FastQC FAIL counts as a reason to discard a sample without opening the module.",
      ],
      limitations: "Only imported read files enter the per-sample values; derived files appear in the sample overview and in the filtering column. Pooled Q30 and GC weight each file by its bases, so in a hybrid sample they are dominated by the technology with more bases. The tables show stored results; they do not re-read the files.",
      advanced: "API: GET /api/v1/projects/{id}/qc-overview (four database queries whatever the number of samples) and GET /api/v1/projects/{id}/qc-overview.csv (UTF-8 with BOM, every cell quoted, text that starts with = + - @, tab or a line break prefixed with an apostrophe). Pooled Q30 = Σ(Q30%ᵢ × basesᵢ) ÷ Σ basesᵢ over FASTQ files; pooled GC = Σ(GC%ᵢ × (basesᵢ − ambiguousᵢ)) ÷ Σ(basesᵢ − ambiguousᵢ). Both equal the value ARVA would compute on the concatenated files.",
    },
    es: {
      title: "Resumen de la secuenciación y resumen de QC del proyecto",
      what: "Dos tablas de resumen. En la pestaña QC de una muestra, el resumen de la secuenciación enumera todos los archivos de la muestra, importados y derivados (filtrados), con lecturas, bases, longitud media, N50, calidad media de lectura, bases ≥ Q30 y GC, y para los archivos de señal cruda POD5 las lecturas y la duración de la señal; un gráfico de barras muestra las bases de cada archivo. En la página del proyecto, el resumen de QC tiene una fila por muestra con los valores principales, el filtrado realizado, los indicadores de FastQC y la verificación con SeqKit.",
      why: "Permiten ver de un vistazo qué archivos y muestras se han analizado, cuántos datos contiene cada uno y dónde conviene mirar con más detalle, antes de abrir cada muestra. La tabla del proyecto se puede ordenar, filtrar por tecnología y descargar como CSV.",
      how: "Solo los análisis completados dan valores, siempre el último completado de cada archivo; lo demás se muestra como — con el motivo (sin calcular, calculándose, fallido). Por archivo, los valores son las estadísticas de lectura propias de ARVA; los de POD5 proceden de la biblioteca pod5. Por muestra, ARVA usa los archivos de lecturas importados (FASTQ/FASTA): las lecturas y las bases son sus sumas; el N50 y la calidad media de lectura son los del archivo importado con más bases (en caso de empate, el importado primero), porque el N50 y una media de calidades por lectura no se pueden combinar entre archivos; las bases ≥ Q30 y el GC se calculan exactamente sobre el conjunto de archivos (Q30 sobre todas las bases de los FASTQ, GC sobre todas las bases no ambiguas). Estos valores solo se muestran cuando todos los archivos de lecturas importados tienen estadísticas, para que una suma nunca sea parcial sin avisar. Profundidad = bases totales ÷ el tamaño de genoma esperado que indicaste al calcular las estadísticas, solo si indicaste el mismo tamaño para todos los archivos de lecturas importados; ARVA nunca supone un tamaño de genoma. El filtrado muestra la última ejecución completada de fastp o Filtlong y la proporción de lecturas y bases conservadas, según las estadísticas de ARVA de sus archivos de salida y de entrada. Los indicadores de FastQC se suman sobre el último informe de cada FASTQ importado. La verificación con SeqKit compara SeqKit con ARVA en cada archivo de lecturas importado: «coincide» cuando se verificaron todos los archivos y todos coinciden, «coincide (n de m archivos)» cuando solo se verificaron algunos y esos coinciden, «difiere» cuando al menos una métrica de al menos un archivo verificado difiere (aunque otros archivos coincidan) y «no ejecutada» cuando no se verificó ningún archivo.",
      interpret: "Compara entre sí muestras de la misma tecnología: el filtro de la tabla ayuda. Diferencias grandes de rendimiento, N50 o calidad entre muestras de una misma corrida suelen indicar problemas de librería o de carga que conviene revisar en la página de la muestra. Los indicadores de FastQC son heurísticas pensadas para librerías de lecturas cortas de genoma completo, no veredictos; un «difiere» en la columna de SeqKit significa que no conviene fiarse de un número hasta explicarlo.",
      next: "Abre una muestra desde la tabla para ver sus estadísticas por archivo, gráficos e informes. Descarga el CSV para guardar el resumen con tus registros; está protegido contra la inyección de fórmulas en hojas de cálculo.",
      mistakes: [
        "Leer el N50 del resumen como el N50 de todas las lecturas de la muestra: es el N50 del archivo importado más grande.",
        "Tomar la profundidad estimada como cobertura medida: supone que todas las bases proceden del genoma objetivo.",
        "Considerar los recuentos FAIL de FastQC motivo para descartar una muestra sin abrir el módulo.",
      ],
      limitations: "Solo los archivos de lecturas importados entran en los valores por muestra; los derivados aparecen en el resumen de la muestra y en la columna de filtrado. Q30 y GC en conjunto ponderan cada archivo por sus bases, así que en una muestra híbrida dominan los de la tecnología con más bases. Las tablas muestran resultados guardados; no vuelven a leer los archivos.",
      advanced: "API: GET /api/v1/projects/{id}/qc-overview (cuatro consultas a la base de datos, sea cual sea el número de muestras) y GET /api/v1/projects/{id}/qc-overview.csv (UTF-8 con BOM, cada celda entre comillas, el texto que empieza por = + - @, tabulador o salto de línea lleva delante un apóstrofo). Q30 en conjunto = Σ(Q30%ᵢ × basesᵢ) ÷ Σ basesᵢ sobre los FASTQ; GC en conjunto = Σ(GC%ᵢ × (basesᵢ − ambiguasᵢ)) ÷ Σ(basesᵢ − ambiguasᵢ). Ambos coinciden con el valor que ARVA calcularía sobre los archivos concatenados.",
    },
  },
];

export const GUIDE_BY_ID = Object.fromEntries(GUIDE.map((g) => [g.id, g])) as Record<GuideId, GuideEntry>;

export function localized(entry: GuideEntry, language: Language): Localized {
  return entry[language] ?? entry.en;
}
