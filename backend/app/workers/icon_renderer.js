const fs = require("fs");
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

const iconSets = {
  Fi: require("react-icons/fi"),
  Fa: require("react-icons/fa"),
  Md: require("react-icons/md"),
  Hi: require("react-icons/hi"),
  Bi: require("react-icons/bi"),
};

function sanitizeColor(hex) {
  const cleaned = String(hex || "000000").replace("#", "").slice(0, 6);
  return /^[0-9a-fA-F]{6}$/.test(cleaned) ? cleaned : "000000";
}

function getIconComponent(iconName) {
  const prefix = String(iconName || "").slice(0, 2);
  const set = iconSets[prefix];
  if (set && set[iconName]) {
    return set[iconName];
  }
  return iconSets.Fa.FaLightbulb;
}

async function renderIcon(iconName, color, outputPath) {
  const Icon = getIconComponent(iconName);
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Icon, {
      color: `#${sanitizeColor(color)}`,
      size: 448,
      style: { display: "block" },
    })
  );
  const pngBuffer = await sharp(Buffer.from(svg))
    .resize(512, 512, {
      fit: "contain",
      background: { r: 255, g: 255, b: 255, alpha: 0 },
    })
    .png()
    .toBuffer();
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, pngBuffer);
}

async function main() {
  const [iconName, color, outputPath] = process.argv.slice(2);
  if (!iconName || !outputPath) {
    throw new Error("Usage: node icon_renderer.js <iconName> <hexColor> <outputPath>");
  }
  await renderIcon(iconName, color, outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
