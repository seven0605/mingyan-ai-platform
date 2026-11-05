import { readFileSync } from "node:fs";

const [, , projectId, assetId, sourceImageId, imagePath] = process.argv;

if (!projectId || !assetId || !sourceImageId || !imagePath) {
  throw new Error(
    "Usage: create-identity-master <project-id> <asset-id> <source-image-id> <png-path>",
  );
}

const imageData = `data:image/png;base64,${readFileSync(imagePath).toString("base64")}`;
const response = await fetch(
  `http://127.0.0.1:8000/api/projects/${projectId}/assets/${assetId}/identity-masters`,
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sourceImageId, imageData }),
  },
);
if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
const library = await response.json();
const asset = library.items.find((item) => item.id === assetId);
console.log(JSON.stringify({
  asset: asset.name,
  identityMasterId: asset.identityMasterId,
  identityMasterUrl: asset.identityMasters.at(-1)?.url,
}, null, 2));
