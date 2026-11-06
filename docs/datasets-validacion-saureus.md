<!-- Relevamiento del 2026-11-06: citas y accesiones verificadas en Europe PMC, ENA y los suplementos abiertos; lo no verificado está marcado. -->

# Datasets recomendados para validar ARVA (*S. aureus*)

Todo lo que aparece aquí salió del informe verificado (Europe PMC, ENA, suplementos abiertos). Lo que **no** se pudo comprobar está marcado como **[NO VERIFICADO]**.

**Aviso general.** Los datasets solo Illumina se ensamblan en ARVA con SPAdes, y los ONT + Illumina se pueden ensamblar también con Unicycler (híbrido). Con 8 GB de RAM conviene submuestrear las lecturas ONT a unas 80-100x antes de Flye.

---

## 1. Chakrawarti 2024: la mejor opción (ONT GridION + Illumina, granjas lecheras)

**Cita:** Chakrawarti A, Eckstrom K, Laaguiby P, Barlow JW. Hybrid Illumina-Nanopore assembly improves identification of multilocus sequence types and antimicrobial resistance genes of *Staphylococcus aureus* isolated from Vermont dairy farms: comparison to Illumina-only and R9.4.1 nanopore-only assemblies. *Access Microbiology* 2024;6(3):000766.v3. DOI **10.1099/acmi.0.000766.v3** (PMID 38725589).

**Accesión:** BioProject **PRJNA983748** (BioSamples SAMN36020147 a SAMN36020208).
- Los 62 aislados del artículo tienen 62 corridas ONT GridION y 62 Illumina MiniSeq.
- El proyecto tiene más corridas que el artículo (101 BioSamples). Hay que usar la **Tabla S1** para mapear cada aislado a su SRX.
- Tamaño: 62 aislados ≈ 32 GB ONT + 1,9 GB Illumina, es decir, unos 0,5 GB de ONT por aislado.

**Origen de los aislados:** 24 humanos, 24 de leche de tanque, 9 de leche de cuarto y 5 de corvejón.

**Qué comparar** (suplemento `acmi-6-00766-s001.xlsx`):
- **ST** de ARVA frente a la MLST por Sanger (S1 y S3), que es la verdad de referencia.
  - En S3, unas 19 de las 62 llamadas con ONT solo no coincidían con Sanger. Ese es el resultado que hay que reproducir o superar.
- **spa** de ARVA frente a la Tabla S5 (spaTyper por método de ensamblaje).
- **Genes AMR** frente al fenotipo de la Tabla S7 (S/I/R para 20 antibióticos, entre ellos penicilina, oxacilina, cefoxitina, pirlimicina y ceftiofur).
  - Los genes AMR del artículo solo están como heatmap (Fig. S1), no como tabla.
- No hay datos de SCCmec, agr ni virulencia.

**Subconjunto sugerido (15-20 aislados):**
- 1-2 aislados por ST: 7083 (ST nuevo), 8, 151, 398, 5, 5957, 352, 7, 2187, 97, 30 y 72.
- Priorizar los aislados de leche.
- Incluir varios de los que fallaron en MLST con ONT solo (S3).
- Incluir aislados resistentes y sensibles según S7.

**Limitaciones:**
- Química R9.4.1 con Flye y Medaka antiguos. Con tu GridION actual seguramente usas R10.4.1, así que los errores esperables son distintos.
- Medaka necesita el modelo correcto para R9.4.1.

---

## 2. Moawad 2023: mastitis bovina, MRSA y MSSA, con salidas de las mismas herramientas (solo Illumina)

**Cita:** Moawad AA, El-Adawy H, Linde J, Jost I, Gärtner T, Hruschka K, Donat K, Neubauer H, Monecke S, Tomaso H. Whole genome sequence-based analysis of *Staphylococcus aureus* isolated from bovine mastitis in Thuringia, Germany. *Frontiers in Microbiology* 2023;14:1216850. DOI **10.3389/fmicb.2023.1216850** (PMID 37692386).

**Accesión:** ENA **PRJEB61659**.
- 40 corridas Illumina MiSeq. El `sample_alias` coincide con el ID del aislado (por ejemplo 20CS0422).
- Tamaño: 7,9 GB.

**Qué comparar** (`Table_1.XLSX`):
- **ST** y perfil alélico (hoja MLST).
- **mecA** frente al estado MRSA/MSSA confirmado por qPCR, E-test y VITEK.
- **AMRFinderPlus**: genes y mutaciones puntuales (hoja `allAMRfinder`).
- **ABRicate VFDB** (hoja `all_vfdb`), más ABRicate ResFinder, CARD y NCBI.
- Fenotipo VITEK de 16 o más antibióticos.
- Plásmidos: en el artículo se calcularon con Platon. Frente a MOB-suite y PlasmidFinder solo sirve como comparación orientativa.
- No hay spa, agr ni tipo SCCmec por aislado.

**Subconjunto sugerido (unos 15):**
- Los 9 aislados que no son ST398.
- Unos 6 ST398 que mezclen MRSA y MSSA.
- En total, 30 de los 40 son MRSA.

**Limitaciones:**
- Solo lecturas cortas: valida la capa de tipificación, AMR y virulencia, no Flye ni Medaka.
- Dominado por ST398 (31 de 40).
- Las versiones de las herramientas son antiguas (AMRFinderPlus 3.6.10, ABRicate 0.8.10). Son normales pequeñas diferencias debidas a la versión de la base de datos.
- Si ENA tiene ensamblados ya hechos de estos aislados: **[NO VERIFICADO]**.

---

## 3. Kaya 2018 (SCCmecFinder): la verdad de referencia para SCCmec

**Cita:** Kaya H, Hasman H, Larsen J, Stegger M, Johannesen TB, Allesøe RL, Lemvigh CK, Aarestrup FM, Lund O, Larsen AR. SCCmecFinder, a web-based tool for typing of staphylococcal cassette chromosome mec in *Staphylococcus aureus* using whole-genome sequence data. *mSphere* 2018;3(1):e00612-17. DOI **10.1128/mSphere.00612-17** (PMID 29468193).

**Accesión:** ENA **PRJEB22380**.
- 93 corridas Illumina: 87 HiSeq 2500 y 6 MiSeq. El `sample_alias` es el ID de la cepa.
- Tamaño: 32,1 GB, unos 0,35 GB por corrida.

**Qué comparar** (Tabla 1 del texto principal, 43 MRSA):
- Tipo **SCCmec** de ARVA frente a la M-PCR de Kondo, que es el estándar de oro.
- También frente a SCCmecFinder, y **ST y spa**.
- Los demás aislados del proyecto no tienen resultado por aislado en la Tabla 1.

**Subconjunto sugerido (10-15 MRSA):** cubrir el mayor número posible de tipos SCCmec distintos de la Tabla 1, incluidos los casos en que SCCmecFinder no coincidió con la PCR.

**Limitaciones:**
- Aislados clínicos humanos de Dinamarca.
- Solo Illumina: se ensambla en ARVA con SPAdes.

---

## 4. Dabernig-Heinz 2024: reproducibilidad con ONT R10.4.1 (opcional)

**Cita:** Dabernig-Heinz J, Lohde M, Hölzer M, Cabal A, Conzemius R, Brandt C, Kohl M, Halbedel S, Hyden P, Fischer MA, Pietzka A, et al. A multicenter study on accuracy and reproducibility of nanopore sequencing-based genotyping of bacterial pathogens. *Journal of Clinical Microbiology* 2024;62(9):e0062824. DOI **10.1128/jcm.00628-24** (PMID 39158309).

**Accesión:** **PRJNA1091452**.
- 18 *S. aureus*, con 136 corridas ONT MinION de varios laboratorios e Illumina del mismo ADN (18 MiSeq y 19 NextSeq 2000).
- Excluir SRR32250912, que está etiquetada como *S. simulans*.
- Tamaño: *S. aureus* ≈ 64,5 GB ONT + 6,8 GB Illumina. El proyecto completo pesa 410 GB, así que hay que filtrar con el filereport de ENA.

**Qué comparar:**
- No trae ST, spa, SCCmec ni AMR por aislado; el criterio del estudio es el cgMLST.
- La referencia se genera corriendo ARVA (con ensamblado externo) sobre las lecturas Illumina.
- Después se mide si ST, spa, SCCmec, agr y AMR salen **idénticos entre las réplicas ONT** de distintos laboratorios.

**Subconjunto sugerido:** 4-5 cepas con 3-4 réplicas ONT cada una, es decir, unas 15-20 corridas.

**Limitaciones:**
- Aislados clínicos, no bovinos.
- Es la opción más cercana a la química actual de tu GridION. Los detalles R10.4.1, SQK-NBD114.24 y Dorado salen del texto y **no se re-verificaron**.

---

## Panel de cepas de referencia

**Opción verificada: Sanderson 2023, MRSA252.**
- Cita: Sanderson ND, Kapel N, Rodger G, Webster H, Lipworth S, Street TL, Peto T, Crook D, Stoesser N. Comparison of R9.4.1/Kit10 and R10/Kit12 Oxford Nanopore flowcells and chemistries in bacterial genome reconstruction. *Microbial Genomics* 2023;9(1). DOI **10.1099/mgen.0.000910** (PMID 36748454).
- Accesión: ENA **PRJEB51164**. Contiene GridION R9 y R10.4 de una sola cepa más una corrida Illumina (ERR9285290).
- Corridas con FASTQ utilizable:
  - ERR8958852 (R9)
  - ERR8958848 (R10.4)
  - ERR8958843 (R10.4 SUP)
  - ERR12813215 (Dorado 0.5.3)
  - ERR12342518
  - 5 de las corridas son solo fast5.
- Verdad de referencia: el genoma cerrado **NC_002952**.
- Sirve como control positivo y prueba de regresión entre químicas, no como benchmark de tipificación.
- Los tipos esperados de MRSA252 (ST, spa, SCCmec, agr) **[NO VERIFICADOS]**: tomarlos de RefSeq o de la literatura.

**Alternativa con más cepas: Ponce Benavente 2024.**
- Cita: *Front Microbiol* 2024;15:1372325, DOI **10.3389/fmicb.2024.1372325**.
- Accesión: **PRJNA952137**, con 72 *S. aureus* en ONT MinION + Illumina MiniSeq (37,3 GB).
- Incluiría COL, Mu50, USA300 y ATCC 29213/43300, pero los **nombres de cepa [NO VERIFICADOS]**.
- El artículo no publica tipificación, así que la verdad de referencia tendría que salir de los genomas RefSeq de esas cepas.

---

## Otros datasets para módulos concretos

| Módulo de ARVA | Dataset | DOI | Accesión | Verdad de referencia | Limitación |
|---|---|---|---|---|---|
| AgrVATE | Raghuram 2022 | 10.1128/spectrum.01334-21 | PRJNA480016 y PRJNA742745 | Grupo agr por cepa (Data Set S1 y Tabla S1) | — |
| spaTyper | Mollerup 2022 | 10.1128/spectrum.02189-22 | PRJNA839593 | spa por Sanger | 1.754 MRSA humanos; hay que submuestrear |
| Tipificación y AMR en mastitis | Majumder 2023 | 10.1186/s12866-023-02785-1 | PRJNA609123 y PRJNA622791 | ST, genes AMR, virulencia y AST por aislado | Solo Illumina; en PRJNA622791 los aislados se identifican por `library_name` |
| Química actual del GridION | Vereecke 2025 | 10.1128/jcm.00664-25 | PRJNA1255637 | No trae tipificación | 10 *S. aureus* en GridION R10.4.1 + iSeq |

**No recomendados:** Haugan 2026, porque es un preprint sin revisión por pares, y Ferreira 2021, porque no tiene lecturas ONT crudas.

**Orden de trabajo sugerido:** primero Chakrawarti (ST, spa y AST con ONT), luego Moawad (AMR y VFDB en mastitis), luego Kaya (SCCmec) y, si queda capacidad, Dabernig-Heinz (reproducibilidad con R10.4.1).
