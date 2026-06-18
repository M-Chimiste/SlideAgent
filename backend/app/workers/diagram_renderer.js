const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

async function renderDiagram(svgPath, outputPath, width, height) {
  const svg = fs.readFileSync(svgPath);
  const pngBuffer = await sharp(svg, { density: 192 })
    .resize(width, height, {
      fit: "contain",
      background: { r: 255, g: 255, b: 255, alpha: 0 },
    })
    .png()
    .toBuffer();
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, pngBuffer);
}

async function main() {
  const [svgPath, outputPath, widthRaw, heightRaw] = process.argv.slice(2);
  if (!svgPath || !outputPath) {
    throw new Error("Usage: node diagram_renderer.js <input.svg> <output.png> [width] [height]");
  }
  const width = Number.parseInt(widthRaw || "1920", 10);
  const height = Number.parseInt(heightRaw || "1040", 10);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("Diagram raster dimensions must be positive integers");
  }
  await renderDiagram(svgPath, outputPath, width, height);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
