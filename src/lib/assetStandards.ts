import type {
  AssetStandardSettings,
  AssetVisualStandard,
  CostumeEra,
} from "../types";

export interface VisualStandardOption {
  id: AssetVisualStandard;
  label: string;
  shortLabel: string;
  summary: string;
  layout: string;
  compatibleWithChineseCostume: boolean;
}

export interface CostumeEraOption {
  id: CostumeEra;
  label: string;
  detail: "detailed" | "foundation" | "unset";
}

export const DEFAULT_ASSET_STANDARD: AssetStandardSettings = {
  visualStandard: "live-action",
  costumeEra: "auto",
};

export const ASSET_PROMPT_TEMPLATE_VERSION = "2026-11-04.1";

export function assetStandardSignature(settings: AssetStandardSettings) {
  return `${settings.visualStandard}|${settings.costumeEra}|${ASSET_PROMPT_TEMPLATE_VERSION}`;
}

export function assetAspectRatio(
  standard: AssetVisualStandard,
  kind: "character" | "scene" | "prop",
) {
  if (standard === "western-dark-medieval") return "16:9";
  if (standard === "victorian-gothic") return kind === "character" ? "9:16" : "16:9";
  if (standard === "guofeng-3d") return kind === "character" ? "9:16" : "16:9";
  return kind === "scene" ? "16:9" : "9:16";
}

export const VISUAL_STANDARD_OPTIONS: VisualStandardOption[] = [
  {
    id: "live-action",
    label: "真人写实 · 通用资产卡",
    shortLabel: "真人写实",
    summary: "真实演员、皮肤与服装材质，强调同一角色和实拍制作感。",
    layout: "人物 9:16 四宫格；场景 16:9 五视图；物品 9:16 细节与全貌。",
    compatibleWithChineseCostume: true,
  },
  {
    id: "guofeng-3d",
    label: "国风 3D 动画",
    shortLabel: "国风 3D",
    summary: "国风审美、PBR 材质与皮肤 SSS，适合高品质三维漫剧资产。",
    layout: "沿用稳定多视图资产板式，风格层使用国风 3D 材质与电影光影。",
    compatibleWithChineseCostume: true,
  },
  {
    id: "handpainted-3d2d",
    label: "手绘 3 渲 2",
    shortLabel: "手绘 3 渲 2",
    summary: "非真人造型、单主光、分块明暗、手绘纹理与选择性描边。",
    layout: "人物、场景、物品分别使用固定多视图；禁用照片级 PBR 与塑料感。",
    compatibleWithChineseCostume: true,
  },
  {
    id: "western-dark-medieval",
    label: "西方真人 · 暗黑中世纪",
    shortLabel: "西方暗黑中世纪",
    summary: "冷峻、做旧、实拍质感的中世纪奇幻制作资产，不绑定真实单一朝代。",
    layout: "16:9 制作板，覆盖角色、服装、场景、怪物与道具的多视图和材质信息。",
    compatibleWithChineseCostume: false,
  },
  {
    id: "victorian-gothic",
    label: "西方真人 · 维多利亚",
    shortLabel: "维多利亚真人",
    summary: "1837—1901 年英国维多利亚时代暗黑奇幻，按早、中、晚期校验。",
    layout: "人物使用 9:16 四宫格，其余资产使用 16:9 制作板并锁定年代技术边界。",
    compatibleWithChineseCostume: false,
  },
];

export const COSTUME_ERA_OPTIONS: CostumeEraOption[] = [
  { id: "auto", label: "未指定朝代", detail: "unset" },
  { id: "xia", label: "夏", detail: "foundation" },
  { id: "shang", label: "商", detail: "foundation" },
  { id: "zhou", label: "周", detail: "foundation" },
  { id: "qin", label: "秦", detail: "foundation" },
  { id: "han", label: "汉", detail: "detailed" },
  { id: "three-kingdoms", label: "三国", detail: "foundation" },
  { id: "jin", label: "晋", detail: "foundation" },
  { id: "northern-southern", label: "南北朝", detail: "foundation" },
  { id: "sui", label: "隋", detail: "foundation" },
  { id: "tang", label: "唐", detail: "detailed" },
  { id: "five-dynasties", label: "五代十国", detail: "foundation" },
  { id: "song", label: "宋", detail: "detailed" },
  { id: "yuan", label: "元", detail: "foundation" },
  { id: "ming", label: "明", detail: "detailed" },
  { id: "qing", label: "清", detail: "foundation" },
];
