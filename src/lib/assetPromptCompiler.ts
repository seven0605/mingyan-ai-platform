import type {
  AssetItem,
  AssetKind,
  AssetStandardSettings,
  AssetVisualStandard,
  CostumeEra,
} from "../types";
import {
  COSTUME_ERA_OPTIONS,
  VISUAL_STANDARD_OPTIONS,
} from "./assetStandards";

export interface CompiledAssetPrompt {
  prompt: string;
  warnings: string[];
  standardLabel: string;
  eraLabel: string | null;
}

const KIND_LABELS: Record<AssetKind, string> = {
  character: "角色",
  scene: "场景",
  prop: "物品",
};

const GENERIC_LAYOUTS: Record<AssetKind, string> = {
  character: "9:16 竖版 2×2 四宫格资产卡。上部约 42%，左格为正面头肩近景，右格为严格 90° 侧面头肩近景；下部约 58%，左格为无头正面服装全貌，右格为完整背面全身。四格必须是同一身份、同一套造型。",
  scene: "16:9 横版五视图场景资产板：正向、反向、左向、右向与俯视线稿平面关系。五个视图必须保持建筑结构、出入口、关键陈设和空间尺度一致；只使用无文字的视觉分区。",
  prop: "9:16 竖版 2×2 物品资产卡。上部展示材质、结构与关键纹样细节，下部展示两个可校验完整轮廓的不同角度；同一物品、同一磨损状态、无人手持。",
};

const PRODUCTION_BOARD_LAYOUTS: Record<AssetKind, string> = {
  character: "16:9 横版角色制作板，包含正面、严格侧面、背面与服装/材质细节；所有视图必须保持同一演员身份、体貌、服装层级和做旧状态。",
  scene: "16:9 横版场景制作板，包含正向、反向、左右向与俯视空间关系；锁定建筑结构、路径、关键陈设、天气和材质状态。",
  prop: "16:9 横版道具制作板，包含正面、侧面、背面、结构拆解与材质细节；锁定尺寸比例、工艺、磨损与年代状态，无人手持。",
};

const STYLE_RULES: Record<AssetVisualStandard, string> = {
  "live-action": "真人实拍制作质感。角色使用真实演员与自然皮肤纹理；场景和物品使用可信的实体材质、真实尺度与克制的电影光线。避免照片级细节被磨平，不使用 3D 渲染、CG 塑料感或游戏引擎画面。",
  "guofeng-3d": "高品质国风 3D 动画资产。造型具有中国审美的明确轮廓，使用可信 PBR 材质、皮肤次表面散射和克制的电影级光影；细节服务于角色与叙事，不做真人摄影或廉价塑料玩具感。",
  "handpainted-3d2d": "手绘 3 渲 2 动画资产。先锁定非真人化的大形与辨识轮廓；只设一个明确主光，将明暗归纳为 2—3 个大色块；材质为哑光手绘纹理，使用有粗细变化的深灰或棕色选择性描边。禁止照片级 PBR、塑料高光、HDRI 主导照明和多个主光源。",
  "western-dark-medieval": "西方暗黑中世纪奇幻真人电影资产。采用真实演员、实体服装、实景与可制作道具，材质寒冷、克制、长期使用并自然做旧；保持低饱和层次和可信火光/天光。禁止现代合成材料、3D/CG、游戏引擎感和对具体影视 IP 的模仿。",
  "victorian-gothic": "1837—1901 年英国维多利亚时代暗黑奇幻真人电影资产。使用真实演员、实体服装、实景和可制作道具，按身份与早/中/晚期控制轮廓、面料、工艺与技术边界；光线可体现煤烟、阴天或煤气灯环境。禁止现代技术、无依据的蒸汽朋克机械堆砌、3D/CG 和游戏引擎感。",
};

const DETAILED_ERA_RULES: Partial<Record<CostumeEra, string>> = {
  han: "汉代精细服饰层：按人物身份选用深衣（曲裾或直裾）等合适形制，交领右衽、宽袖，面料与配色服从身份和场景。禁止唐代圆领袍与幞头、明代补子与网巾等跨代元素。",
  tang: "唐代精细服饰层：男性可按身份使用圆领袍与幞头，女性可按身份使用襦裙体系；品色、面料、头饰和配饰必须与阶层相符。禁止明代补子、网巾等跨代元素。",
  song: "宋代精细服饰层：按身份选用圆领袍、直裰或褙子等合适形制，整体审美清雅克制，可使用幞头或巾帻等匹配头饰。禁止明代补子、网巾、马面裙等跨代元素。",
  ming: "明代精细服饰层：按身份与性别选用圆领袍、补服或马面裙等合适形制；男性网巾、官员补子等元素只在身份成立时使用。禁止清代旗袍、马蹄袖等跨代元素。",
};

function layoutFor(standard: AssetVisualStandard, kind: AssetKind) {
  if (standard === "western-dark-medieval") return PRODUCTION_BOARD_LAYOUTS[kind];
  if (standard === "victorian-gothic" && kind !== "character") {
    return PRODUCTION_BOARD_LAYOUTS[kind];
  }
  return GENERIC_LAYOUTS[kind];
}

function costumeLayer(
  standard: AssetVisualStandard,
  era: CostumeEra,
  kind: AssetKind,
): { rule: string | null; warning: string | null; eraLabel: string | null } {
  const standardOption = VISUAL_STANDARD_OPTIONS.find((option) => option.id === standard);
  if (!standardOption?.compatibleWithChineseCostume) {
    return { rule: null, warning: null, eraLabel: null };
  }

  const eraOption = COSTUME_ERA_OPTIONS.find((option) => option.id === era)
    ?? COSTUME_ERA_OPTIONS[0];
  if (era === "auto") {
    return {
      rule: "未指定中国朝代，不自动添加具体形制、品色、头饰或配饰。若画面涉及古代服饰，生成前需要人工确定年代。",
      warning: "尚未指定中国朝代，本次预览不会自动套用具体服饰规则。",
      eraLabel: eraOption.label,
    };
  }

  const detailedRule = DETAILED_ERA_RULES[era];
  if (detailedRule) {
    return {
      rule: kind === "character" ? detailedRule : `画面若出现人物，${detailedRule}`,
      warning: null,
      eraLabel: eraOption.label,
    };
  }

  return {
    rule: `锁定为${eraOption.label}代语境，但现有资料尚未达到精细规则级别；不自动推断具体形制、品色、面料或头饰，正式生成前必须人工补充考据。`,
    warning: `${eraOption.label}代目前只有基础资料，本预览不会杜撰具体服饰细节。`,
    eraLabel: eraOption.label,
  };
}

function sourceLine(label: string, value: string) {
  const cleaned = value.trim();
  return cleaned ? `${label}：${cleaned}` : `${label}：待补充`;
}

export function compileAssetPrompt(
  item: AssetItem,
  settings: AssetStandardSettings,
): CompiledAssetPrompt {
  const standard = VISUAL_STANDARD_OPTIONS.find(
    (option) => option.id === settings.visualStandard,
  ) ?? VISUAL_STANDARD_OPTIONS[0];
  const costume = costumeLayer(
    settings.visualStandard,
    settings.costumeEra,
    item.kind,
  );
  const warnings = costume.warning ? [costume.warning] : [];
  const sections = [
    `【输出目标】${KIND_LABELS[item.kind]}资产卡｜${item.name}`,
    [
      "【内容依据】",
      sourceLine("剧本说明", item.description),
      sourceLine("视觉锚点", item.visualAnchor),
      sourceLine("连续性约束", item.continuityNotes),
    ].join("\n"),
    `【版式与视图】\n${layoutFor(settings.visualStandard, item.kind)}`,
    `【视觉标准】\n${STYLE_RULES[settings.visualStandard]}`,
    costume.rule ? `【历史服饰层】\n${costume.rule}` : null,
    `【一致性硬约束】\n所有视图必须保持主体身份、比例、结构、颜色、材质与标志性细节一致；不得用不同设计填充不同分格。${item.kind === "character" ? "角色脸部、发型、身形和服装层级不得漂移。" : "空间或物品的结构关系不得漂移。"}`,
    `【禁止项】\n禁止多余主体、视角重复、结构畸变、版式错乱、无依据的设计增补、文字、字母、数字、标签、Logo、水印和边框标题。`,
  ].filter((section): section is string => Boolean(section));

  return {
    prompt: sections.join("\n\n"),
    warnings,
    standardLabel: standard.label,
    eraLabel: costume.eraLabel,
  };
}
