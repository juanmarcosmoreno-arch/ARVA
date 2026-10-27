import {
  BarChart3,
  BookOpen,
  Boxes,
  Dna,
  FileText,
  FlaskConical,
  FolderKanban,
  GitBranch,
  GitCompareArrows,
  LayoutDashboard,
  Map as MapIcon,
  Microscope,
  Puzzle,
  Settings,
  Upload,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { TranslationKey } from "@/i18n";

export interface NavItem {
  key: string;
  label: TranslationKey;
  icon: LucideIcon;
  to: string;
  /** Roadmap phase in which the module becomes available; undefined = available now. */
  plannedPhase?: number | string;
  description?: string;
}

export interface NavSection {
  label?: TranslationKey;
  items: NavItem[];
}

export const NAV: NavSection[] = [
  {
    items: [
      { key: "dashboard", label: "nav.dashboard", icon: LayoutDashboard, to: "/" },
      { key: "projects", label: "nav.projects", icon: FolderKanban, to: "/projects" },
      { key: "samples", label: "nav.samples", icon: FlaskConical, to: "/samples" },
      { key: "import", label: "nav.import", icon: Upload, to: "/import" },
      { key: "qc", label: "nav.qc", icon: BarChart3, to: "/qc" },
    ],
  },
  {
    label: "nav.section.analysis",
    items: [
      { key: "assembly", label: "nav.assembly", icon: Puzzle, to: "/modules/assembly", plannedPhase: 3,
        description: "Long-read, short-read and hybrid assembly (Flye first), with QUAST evaluation and contig statistics." },
      { key: "annotation", label: "nav.annotation", icon: Dna, to: "/modules/annotation", plannedPhase: 4,
        description: "Genome annotation with Bakta (Prokka as alternative), gene browser and FASTA/GFF3/GenBank export." },
      { key: "genomic", label: "nav.genomic", icon: Microscope, to: "/modules/genomic", plannedPhase: 5,
        description: "MLST, AMRFinderPlus resistome, virulome, BLAST search and taxonomic identification." },
      { key: "explorer", label: "nav.explorer", icon: MapIcon, to: "/modules/explorer", plannedPhase: 4,
        description: "Interactive linear and circular genome browser with annotation, GC, coverage and feature tracks." },
      { key: "comparative", label: "nav.comparative", icon: GitCompareArrows, to: "/modules/comparative", plannedPhase: 6,
        description: "ANI, synteny, dot plots and the gene-neighbourhood Region Explorer across genomes." },
      { key: "phylogeny", label: "nav.phylogeny", icon: GitBranch, to: "/modules/phylogeny", plannedPhase: 7,
        description: "MAFFT + IQ-TREE phylogenies with an interactive, metadata-aware Tree Explorer." },
      { key: "pangenome", label: "nav.pangenome", icon: Boxes, to: "/modules/pangenome", plannedPhase: 7,
        description: "Panaroo pangenome, presence/absence matrices and accumulation curves." },
    ],
  },
  {
    label: "nav.section.platform",
    items: [
      { key: "workflows", label: "nav.workflows", icon: Workflow, to: "/modules/workflows", plannedPhase: 8,
        description: "Visual workflow builder backed by Nextflow DSL2, with predefined bacterial pipelines." },
      { key: "reports", label: "nav.reports", icon: FileText, to: "/reports" },
      { key: "tools", label: "nav.tools", icon: Wrench, to: "/modules/tools", plannedPhase: "3+",
        description: "Tool and database manager: versions, licences, integrity checks and controlled installation." },
      { key: "guide", label: "nav.guide", icon: BookOpen, to: "/guide" },
      { key: "settings", label: "nav.settings", icon: Settings, to: "/settings" },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((s) => s.items);
