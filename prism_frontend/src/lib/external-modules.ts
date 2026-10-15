import type { ComponentType } from "react";
import { Sparkles } from "lucide-react";

export interface ExternalModule {
  id: string;
  label: string;
  description: string;
  href: string;
  // 图标统一为可接收 className 的组件,兼容 lucide SVG 图标。
  icon: ComponentType<{ className?: string }>;
  category: string;
  keywords: string[];
}

export const externalModules: ExternalModule[] = [
  {
    id: "ai-fusion",
    label: "AI-Fusion",
    description: "融合能力中心",
    href: "/fusion",
    icon: Sparkles,
    category: "智能",
    keywords: ["fusion", "ai", "ai-fusion", "融合", "智能体"],
  },
];
