import { compileAssetPrompt } from "../src/lib/assetPromptCompiler";
import { assetStandardSignature } from "../src/lib/assetStandards";

const [, , projectId, ...requestedNames] = process.argv;

if (!projectId || requestedNames.length === 0) {
  throw new Error("Usage: prepare-asset-batch <project-id> <asset-name> [...]");
}

const apiRoot = "http://127.0.0.1:8000";
const standard = {
  visualStandard: "live-action",
  costumeEra: "ming",
} as const;

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${apiRoot}${path}`, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json();
}

const library = await request(`/api/projects/${projectId}/assets`);
if (!library) throw new Error("Asset library is missing");

const signature = assetStandardSignature(standard);
const requested = new Set(requestedNames);
const anchorOverrides: Record<string, string> = {
  "司沧的长刀": "明代军用长刀，玄黑木质刀鞘，低调哑光铜制护手与刀镡，刀身修长锋利，尺寸适合成年男性腰佩实战；不得使用日式刀镡、弧度或现代合金装饰。",
};
const preparedItems = library.items.map((item: any) => {
  const normalized = requested.has(item.name) && !item.visualAnchor.trim()
    ? { ...item, visualAnchor: anchorOverrides[item.name] ?? `${item.name}的历史写实形制与材质细节` }
    : item;
  return {
    ...normalized,
    referencePrompt: compileAssetPrompt(normalized, standard).prompt,
    promptStandardSignature: signature,
    status: requested.has(item.name) || item.referenceImages.length ? "confirmed" : "draft",
  };
});

const saved = await request(`/api/projects/${projectId}/assets`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ standard, items: preparedItems }),
});
const assetsByName = new Map(saved.items.map((item: any) => [item.name, item]));
const missing = requestedNames.filter((name) => !assetsByName.has(name));
if (missing.length) throw new Error(`Missing assets: ${missing.join(", ")}`);

const plan = await request(`/api/projects/${projectId}/assets/batch-plan`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    assetIds: requestedNames.map((name) => (assetsByName.get(name) as any).id),
  }),
});

console.log(JSON.stringify({
  standard: saved.standard,
  totalAssets: saved.items.length,
  selected: plan.items.map((item: any) => ({
    name: item.name,
    kind: item.assetKind,
    aspectRatio: item.aspectRatio,
  })),
}, null, 2));
