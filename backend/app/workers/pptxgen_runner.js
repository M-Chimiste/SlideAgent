const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

const iconSets = {
  Fa: require("react-icons/fa"),
  Md: require("react-icons/md"),
  Hi: require("react-icons/hi"),
  Bi: require("react-icons/bi"),
};

function sanitizeColor(hex) {
  if (!hex) return "000000";
  return hex.replace("#", "").slice(0, 6);
}

function getIconComponent(iconName) {
  const prefix = iconName.slice(0, 2);
  const set = iconSets[prefix];
  if (set && set[iconName]) {
    return set[iconName];
  }
  return iconSets.Fa.FaLightbulb;
}

const iconCache = new Map();

async function renderIconBase64(iconName, color) {
  const cacheKey = `${iconName}-${color}`;
  if (iconCache.has(cacheKey)) {
    return iconCache.get(cacheKey);
  }
  const Icon = getIconComponent(iconName);
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(Icon, { color, size: 128 })
  );
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  const base64 = pngBuffer.toString("base64");
  iconCache.set(cacheKey, base64);
  return base64;
}

function addTitle(slide, title, brand) {
  slide.addText(title, {
    x: 0.6,
    y: 0.4,
    w: 12.2,
    h: 0.6,
    fontSize: 36,
    bold: true,
    color: sanitizeColor(brand.colors.text_dark),
  });
}

async function addIconRows(slide, slideData, brand) {
  const items = slideData.bullets?.length ? slideData.bullets : [slideData.summary];
  const icons = slideData.icons || [];
  let y = 1.4;
  for (let i = 0; i < Math.min(items.length, 3); i += 1) {
    const iconName = icons[i] || icons[0] || "FaLightbulb";
    const base64 = await renderIconBase64(iconName, `#${sanitizeColor(brand.colors.accent)}`);
    slide.addShape(pptxgen.ShapeType.ellipse, {
      x: 0.8,
      y,
      w: 0.5,
      h: 0.5,
      fill: { color: sanitizeColor(brand.colors.accent) },
      line: { color: sanitizeColor(brand.colors.accent) },
    });
    slide.addImage({
      data: `data:image/png;base64,${base64}`,
      x: 0.84,
      y: y + 0.05,
      w: 0.4,
      h: 0.4,
    });
    slide.addText(items[i], {
      x: 1.5,
      y,
      w: 11.0,
      h: 0.6,
      fontSize: 16,
      color: sanitizeColor(brand.colors.text_dark),
      valign: "top",
    });
    y += 1.1;
  }
}

function addCallouts(slide, slideData, brand) {
  const metrics = slideData.metrics || [];
  let x = 0.8;
  for (let i = 0; i < Math.min(metrics.length, 3); i += 1) {
    const metric = metrics[i];
    slide.addShape(pptxgen.ShapeType.rect, {
      x,
      y: 1.6,
      w: 3.6,
      h: 2.0,
      fill: { color: sanitizeColor(brand.colors.background_light) },
      line: { color: sanitizeColor(brand.colors.secondary) },
    });
    slide.addText(String(metric.value), {
      x: x + 0.2,
      y: 1.9,
      w: 3.2,
      h: 0.8,
      fontSize: 44,
      bold: true,
      color: sanitizeColor(brand.colors.primary),
      align: "center",
    });
    slide.addText(metric.label || "Metric", {
      x: x + 0.2,
      y: 2.8,
      w: 3.2,
      h: 0.4,
      fontSize: 12,
      color: sanitizeColor(brand.colors.text_dark),
      align: "center",
    });
    x += 4.0;
  }
}

function addTwoColumn(slide, slideData, brand) {
  const leftText = slideData.summary || "";
  const bullets = slideData.bullets || [];
  slide.addText(leftText, {
    x: 0.8,
    y: 1.6,
    w: 5.8,
    h: 4.8,
    fontSize: 16,
    color: sanitizeColor(brand.colors.text_dark),
  });
  slide.addText(
    bullets.map((item) => ({ text: item, options: { bullet: true, breakLine: true } })),
    {
      x: 7.0,
      y: 1.6,
      w: 5.8,
      h: 4.8,
      fontSize: 16,
      color: sanitizeColor(brand.colors.text_dark),
      margin: 0,
    }
  );
}

function addChart(slide, slideData, brand) {
  const metrics = slideData.metrics || [];
  const data = [
    {
      name: "Values",
      labels: metrics.map((metric) => metric.label || "Metric"),
      values: metrics.map((metric) => metric.value || 0),
    },
  ];
  slide.addChart(pptxgen.ChartType.bar, data, {
    x: 0.8,
    y: 1.6,
    w: 11.8,
    h: 4.8,
    barDir: "col",
    chartColors: [sanitizeColor(brand.colors.primary)],
    dataLabelColor: sanitizeColor(brand.colors.text_dark),
  });
}

async function addIconGrid(slide, slideData, brand) {
  const items = slideData.bullets?.length ? slideData.bullets : [slideData.summary];
  const icons = slideData.icons || [];
  const grid = items.slice(0, 4);
  let idx = 0;
  for (let row = 0; row < 2; row += 1) {
    for (let col = 0; col < 2; col += 1) {
      if (idx >= grid.length) break;
      const iconName = icons[idx] || icons[0] || "FaLightbulb";
      const base64 = await renderIconBase64(iconName, `#${sanitizeColor(brand.colors.accent)}`);
      const x = 0.9 + col * 6.0;
      const y = 1.6 + row * 2.2;
      slide.addShape(pptxgen.ShapeType.ellipse, {
        x,
        y,
        w: 0.6,
        h: 0.6,
        fill: { color: sanitizeColor(brand.colors.accent) },
        line: { color: sanitizeColor(brand.colors.accent) },
      });
      slide.addImage({
        data: `data:image/png;base64,${base64}`,
        x: x + 0.08,
        y: y + 0.08,
        w: 0.44,
        h: 0.44,
      });
      slide.addText(grid[idx], {
        x: x + 0.8,
        y,
        w: 4.8,
        h: 0.8,
        fontSize: 16,
        color: sanitizeColor(brand.colors.text_dark),
      });
      idx += 1;
    }
  }
}

async function buildDeck(inputPath, outputPath) {
  const payload = JSON.parse(fs.readFileSync(inputPath, "utf-8"));
  const pptx = new pptxgen();
  pptx.layout = "LAYOUT_WIDE";
  pptx.theme = {
    headFontFace: payload.brand.fonts.heading,
    bodyFontFace: payload.brand.fonts.body,
  };
  for (const slideData of payload.slides) {
    const slide = pptx.addSlide();
    addTitle(slide, slideData.title || "Slide", payload.brand);
    if (slideData.layout === "callouts") {
      addCallouts(slide, slideData, payload.brand);
    } else if (slideData.layout === "two_column") {
      addTwoColumn(slide, slideData, payload.brand);
    } else if (slideData.layout === "chart") {
      addChart(slide, slideData, payload.brand);
    } else if (slideData.layout === "icon_grid") {
      await addIconGrid(slide, slideData, payload.brand);
    } else {
      await addIconRows(slide, slideData, payload.brand);
    }
  }
  await pptx.writeFile({ fileName: outputPath });
}

async function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) {
    throw new Error("Usage: node pptxgen_runner.js <input.json> <output.pptx>");
  }
  await buildDeck(inputPath, outputPath);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
