# Plan: módulo de secuenciación Sanger de un gen

Pedido del usuario (2026-11-03), para hacer **después** de la actualización de versiones y Medaka y de la prueba de la
cepa 27: "es importante".

## Qué hace hoy el usuario

Amplifica un gen por PCR y lo manda a secuenciar por Sanger, por ejemplo a Macrogen (Corea). Macrogen devuelve por
cada lectura un cromatograma `.ab1`, un `.pdf` del cromatograma y un `.txt` con la secuencia FASTA llamada por el
equipo. Hay una lectura forward y otra reverse, por ejemplo `1-27_784-F` y `1-27_1401-R`: 16S rRNA con los
cebadores 784F y 1401R, de la cepa 27.

Genes que manda:

- 16S rRNA;
- enterotoxinas estafilocócicas;
- hemolisinas *hla* y *hlb*;
- genes de biofilm (*ica*, confirmado) y otras proteínas de adhesión;
- y **cualquier otro gen**: el módulo no debe depender de una lista. Los genes nombrados sirven solo como casos de
  prueba y para elegir qué bases se consultan por omisión.

## Lo que pide

1. **Que ARVA diga qué es aunque no se le diga qué gen es.** Debe comparar contra todas las bases locales y dar el
   mejor resultado con **porcentaje de identidad y cobertura**.
2. **Que se pueda poner lo que se sospecha**, gen o especie, y que ARVA diga si coincide o no, y con qué números.

## Diseño propuesto

- **Entrada:** `.ab1` (forward/reverse, emparejados por nombre o a mano); también FASTA o `.seq` sin
  cromatograma, avisando que no hay calidades.
- **Calidad:** visor de cromatograma (picos, calidad por base, bases ambiguas o dobles picos) y recorte de
  extremos de mala calidad con un método publicado (por ejemplo el recorte de Mott que usa Phred), con los
  parámetros a la vista.
  - En el ejemplo `1-27_784-F`, el `.txt` de Macrogen tiene 1.541 bases, pero después de unas 600 la secuencia
    se vuelve ruido (poli-A, picos sin sentido).
  - Por eso el recorte es imprescindible, y la longitud útil debe mostrarse.
- **Consenso F+R:** revertir y complementar la reverse, alinear, resolver diferencias mirando las calidades y
  listar las posiciones en conflicto para revisarlas.
- **Identificación sin decir qué es, de cualquier gen**, contra bases locales y sin enviar nada afuera. La búsqueda
  principal va contra los **genomas completos** de la colección de referencia, y de cualquier genoma que el usuario
  tenga en ARVA, con su anotación (Bakta/GFF). Así cualquier gen presente en esos genomas se encuentra y se nombra
  por su anotación, aunque no esté en una base especializada. Las bases especializadas suman la interpretación:
  - 16S de cepas tipo: base de NCBI "16S ribosomal RNA" (RefSeq de cepas tipo), descargable con versión, como
    las demás bases del gestor;
  - colección de genomas de referencia del usuario (183 *Staphylococcus*): regiones homólogas;
  - VFDB (ya incluida con ABRicate) para enterotoxinas, hemolisinas y biofilm;
  - AMRFinderPlus (ya instalado);
  - esquemas MLST (alelos) y spa (repeticiones), ya incluidos.

  El resultado muestra el mejor resultado y los siguientes, con identidad, cobertura de la consulta y del gen, y
  la base con su versión.
- **Lo que sospecha el usuario:** un campo opcional (gen o especie esperados). ARVA responde *coincide / no
  coincide / ambiguo* con los números, y nunca oculta un resultado mejor que contradiga la sospecha.
- **Interpretación con umbrales publicados y citados:**
  - para 16S, la guía CLSI MM18, con avisos cuando dos especies quedan por encima del umbral;
  - con un fragmento corto de 16S (784F–1401R, unos 600 pb) *Staphylococcus* suele no resolverse a especie, y se
    sugieren genes de mayor resolución (*tuf*, *rpoB*, *sodA*, *gap*).
- **BLAST en NCBI por internet:** solo opcional, con confirmación explícita, porque envía la secuencia afuera.
- **Informe** del resultado (EN/ES) con lecturas, recorte, consenso, bases y versiones, y parámetros.

## Herramientas a evaluar (verificar interfaces antes de usar)

- Lectura de `.ab1`: Biopython (`SeqIO` formato `abi`) desde PyPI.
- Recorte, consenso y alineamiento de trazas: tracy (gear-genomics, Bioconda), u otra herramienta publicada.
- Búsqueda: BLAST+, ya instalado.

## Datos de prueba del usuario

Los `.ab1`, `.pdf` y `.txt` de `1-27_784-F` y `1-27_1401-R` están **fuera del repositorio** (datos del usuario; el
repositorio es público). No se suben a GitHub.
