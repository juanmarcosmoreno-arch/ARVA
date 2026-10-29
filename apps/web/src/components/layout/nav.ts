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
  description?: TranslationKey;
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
      { key: "import", label: "nav.import", icon: Upload, to: "/import", description: "nav.desc.import" },
      { key: "qc", label: "nav.qc", icon: BarChart3, to: "/qc", description: "nav.desc.qc" },
    ],
  },
  {
    label: "nav.section.analysis",
    items: [
      { key: "assembly", label: "nav.assembly", icon: Puzzle, to: "/modules/assembly", plannedPhase: 3,
        description: "nav.desc.assembly" },
      { key: "annotation", label: "nav.annotation", icon: Dna, to: "/modules/annotation", plannedPhase: 4,
        description: "nav.desc.annotation" },
      { key: "genomic", label: "nav.genomic", icon: Microscope, to: "/modules/genomic", plannedPhase: 5,
        description: "nav.desc.genomic" },
      { key: "explorer", label: "nav.explorer", icon: MapIcon, to: "/explorer",
        description: "nav.desc.explorer" },
      { key: "comparative", label: "nav.comparative", icon: GitCompareArrows, to: "/modules/comparative", plannedPhase: 6,
        description: "nav.desc.comparative" },
      { key: "phylogeny", label: "nav.phylogeny", icon: GitBranch, to: "/modules/phylogeny", plannedPhase: 7,
        description: "nav.desc.phylogeny" },
      { key: "pangenome", label: "nav.pangenome", icon: Boxes, to: "/modules/pangenome", plannedPhase: 7,
        description: "nav.desc.pangenome" },
    ],
  },
  {
    label: "nav.section.platform",
    items: [
      { key: "workflows", label: "nav.workflows", icon: Workflow, to: "/modules/workflows", plannedPhase: 8,
        description: "nav.desc.workflows" },
      { key: "reports", label: "nav.reports", icon: FileText, to: "/reports" },
      { key: "tools", label: "nav.tools", icon: Wrench, to: "/tools",
        description: "nav.desc.tools" },
      { key: "guide", label: "nav.guide", icon: BookOpen, to: "/guide" },
      { key: "settings", label: "nav.settings", icon: Settings, to: "/settings" },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((s) => s.items);
