import { expect, Page, test } from "@playwright/test";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAEtAI8Gz0XnQAAAABJRU5ErkJggg==",
  "base64"
);

const now = "2026-06-23T12:00:00Z";

function freeformJob(status: string, progress: number) {
  return {
    id: "job-plan",
    template_id: "__freeform__",
    instructions: "Make the case for structured AI-assisted coding.",
    config_json: {
      generation_mode: "freeform",
      planner_profile: "fast",
      quality_profile: "balanced",
      length_strategy: "auto",
      plan_only: status === "planned",
    },
    status,
    progress,
    qa_rounds: status === "done" ? 1 : 0,
    warnings: [],
    result_file: status === "done" ? "/tmp/output.pptx" : null,
    preview_dir: status === "done" ? "/tmp/preview" : null,
    error_message: null,
    created_at: now,
    completed_at: status === "queued" ? null : now,
  };
}

function planningSummary() {
  return {
    available: true,
    artifacts: ["source-compression", "story-map", "spec-gate"],
    story_map_status: "ready",
    story_map_fallback_reason: null,
    source_coverage: {
      section_count: 6,
      included_section_count: 4,
      omitted_section_count: 2,
      estimated_tokens: 1800,
    },
    spec_gate: {
      status: "repaired",
      issue_count: 2,
      repaired_count: 2,
      unresolved_count: 0,
    },
  };
}

function baseOutline() {
  return [
    {
      slide_index: 0,
      mode: "flexible",
      label: "Old action title",
      action_title: "Old action title",
      subheading: "Original subheading",
      narrative_role: "setup",
      layout: "comparison_table",
      archetype: "comparison_table",
      exhibit_type: "comparison_table",
      sources: ["Uploaded source: Operating model"],
      source_refs: ["sec-001"],
      speaker_notes: "Explain why the current workflow needs a checkpoint.",
      qa_status: "pass",
      qa_issues: [],
    },
    {
      slide_index: 1,
      mode: "flexible",
      label: "Evidence shows review improves reliability",
      action_title: "Evidence shows review improves reliability",
      subheading: "Source-grounded proof points anchor the change",
      narrative_role: "evidence",
      layout: "chart",
      archetype: "chart",
      exhibit_type: "bar_chart",
      sources: ["Uploaded source: QA metrics"],
      source_refs: ["metric-001"],
      speaker_notes: "Show the before and after quality bar.",
      qa_status: "warning",
      qa_issues: [{ category: "density", message: "Check density." }],
    },
  ];
}

async function mockPlanFlow(page: Page) {
  let created = false;
  let renderRequested = false;
  let outline = baseOutline();

  await page.route("**/api/jobs/job-plan/planning/source-compression", (route) =>
    route.fulfill({
      json: {
        section_count: 6,
        included_section_count: 4,
        omitted_section_count: 2,
        estimated_tokens: 1800,
      },
    })
  );
  await page.route("**/api/jobs/job-plan/planning/story-map", (route) =>
    route.fulfill({
      json: {
        status: "ready",
        beats: [
          { role: "setup", preferred_exhibit: "comparison_table" },
          { role: "evidence", preferred_exhibit: "bar_chart" },
        ],
      },
    })
  );
  await page.route("**/api/jobs/job-plan/planning/spec-gate", (route) =>
    route.fulfill({
      json: { status: "repaired", issue_count: 2, repaired_count: 2, unresolved_count: 0 },
    })
  );
  await page.route("**/api/jobs/job-plan/outline", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = JSON.parse(route.request().postData() || "{}");
      const edits = Array.isArray(body.slides) ? body.slides : [];
      outline = outline.map((slide) => {
        const edit = edits.find((candidate: any) => candidate.slide_index === slide.slide_index);
        if (!edit) return slide;
        return {
          ...slide,
          label: edit.action_title || slide.label,
          action_title: edit.action_title || slide.action_title,
          subheading: edit.subheading ?? slide.subheading,
        };
      });
    }
    await route.fulfill({ json: { slides: outline } });
  });
  await page.route("**/api/jobs/job-plan/render", async (route) => {
    renderRequested = true;
    await route.fulfill({ json: freeformJob("queued", 0.5) });
  });
  await page.route("**/api/jobs/job-plan/preview/slide-001.jpg", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/jobs/job-plan", (route) => {
    const job = renderRequested ? freeformJob("done", 1) : freeformJob("planned", 0.5);
    route.fulfill({
      json: {
        job,
        warnings: [],
        preview_images: renderRequested ? ["slide-001.jpg"] : [],
        qa_summary: { critical: 0, warning: renderRequested ? 1 : 0, info: 0, count: renderRequested ? 1 : 0 },
        qa_issues: renderRequested
          ? [{ severity: "WARNING", message: "Check density.", slide_index: 1, category: "density" }]
          : [],
        qa_history: renderRequested
          ? [{ round: 0, passed: false, summary: { critical: 0, warning: 1, info: 0, count: 1 } }]
          : [],
        planning_summary: planningSummary(),
      },
    });
  });
  await page.route("**/api/jobs", async (route) => {
    if (route.request().method() === "POST") {
      created = true;
      await route.fulfill({ json: freeformJob("queued", 0) });
      return;
    }
    await route.fulfill({ json: { jobs: created ? [freeformJob(renderRequested ? "done" : "planned", renderRequested ? 1 : 0.5)] : [] } });
  });
  await page.route("**/api/templates", (route) => route.fulfill({ json: { templates: [] } }));
}

async function mockTemplateRoutes(page: Page) {
  await page.route("**/api/jobs", (route) => route.fulfill({ json: { jobs: [] } }));
  await page.route("**/api/templates", (route) => route.fulfill({ json: { templates: [] } }));
  await page.route("**/api/templates/analyze", async (route) => {
    const body = route.request().postData() || "";
    const strict = body.includes("strict");
    await route.fulfill({ json: strict ? strictTemplate() : brandTemplate() });
  });
  await page.route("**/api/templates/brand-template/assets", (route) =>
    route.fulfill({ json: { template_id: "brand-template", thumbnails: ["slide-001.jpg"], logo_available: true } })
  );
  await page.route("**/api/templates/brand-template/thumbnail/slide-001.jpg", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/templates/brand-template/logo", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/templates/strict-template/assets", (route) =>
    route.fulfill({ json: { template_id: "strict-template", thumbnails: [], logo_available: false } })
  );
}

function brandTemplate() {
  return {
    id: "brand-template",
    name: "Brand Template",
    type: "brand",
    brand: {
      colors: {
        primary: "14213D",
        secondary: "44506A",
        accent: "C8893B",
        background_dark: "0D1426",
        background_light: "EAEEF5",
        text_dark: "14213D",
        text_light: "FFFFFF",
      },
      fonts: { heading: "Aptos Display", body: "Aptos" },
      logo: { path: "/tmp/logo.png", placement: "top-right", w: 1.2, h: 0.4 },
      design_notes: "Use compact title bars. Keep footer source labels visible.",
      layout_profile: {},
    },
    slides: [{ index: 0, mode: "flexible", label: "Title", schema: null }],
    source_file: "/tmp/brand.pptx",
    created_at: now,
    updated_at: now,
  };
}

function strictTemplate() {
  return {
    id: "strict-template",
    name: "Strict Template",
    type: "strict",
    brand: brandTemplate().brand,
    slides: [
      {
        index: 0,
        mode: "strict",
        label: "Summary",
        schema: { fields: [{ id: "client_name", type: "text", location: "shape:Client", required: true, max_chars: 80 }] },
      },
      {
        index: 1,
        mode: "strict",
        label: "Timeline",
        schema: { fields: [{ id: "renewal_date", type: "text", location: "shape:Date", required: true, max_chars: 40 }] },
      },
    ],
    source_file: "/tmp/strict.pptx",
    created_at: now,
    updated_at: now,
  };
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("optional plan preview flow supports edit, render, cockpit, and lightbox metadata", async ({ page }) => {
  await mockPlanFlow(page);
  await page.goto("/");

  await page.getByRole("button", { name: /Start brief/ }).click();
  await page.locator("textarea").fill("Make the case for structured AI-assisted coding.");
  await page.getByRole("button", { name: "Preview plan" }).click();
  await expect(page.getByText("Your ghost deck is ready")).toBeVisible();

  await page.getByRole("button", { name: /Review plan/ }).last().click();
  await expect(page.getByRole("heading", { name: /Review the storyline/ })).toBeVisible();
  const firstTitle = page.locator(".sf-plan-grid input").first();
  await expect(firstTitle).toHaveValue("Old action title");
  await firstTitle.fill("Edited action title earns trust");
  await page.getByRole("button", { name: /Save title edits/ }).click();
  await expect(firstTitle).toHaveValue("Edited action title earns trust");

  await page.getByRole("button", { name: /Render deck/ }).click();
  await expect(page.getByText("Your deck is ready")).toBeVisible();
  await page.getByRole("button", { name: /Review deck/ }).last().click();

  await expect(page.getByText("DECK INTELLIGENCE")).toBeVisible();
  await expect(page.getByText("TITLE LADDER")).toBeVisible();
  await expect(page.getByText("Edited action title earns trust")).toBeVisible();
  await expect(page.getByText("QA ISSUES")).toBeVisible();

  await page.locator(".sf-review-grid img").first().click();
  await expect(page.getByText("OUTLINE")).toBeVisible();
  await expect(page.getByText("sec-001")).toBeVisible();
  await expect(page.getByText("Explain why the current workflow needs a checkpoint.")).toBeVisible();
});

test("template setup shows real assets and all strict schema-bearing slides", async ({ page }) => {
  await mockTemplateRoutes(page);
  await page.goto("/");

  await page.getByText("Brand", { exact: true }).click();
  await page.getByRole("button", { name: /Set up template/ }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "brand.pptx",
    mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    buffer: Buffer.from("pptx"),
  });

  await expect(page.getByText("Brand DNA")).toBeVisible();
  await expect(page.locator('img[alt="Extracted logo"]')).toBeVisible();
  await expect(page.locator('img[alt="slide-001.jpg"]')).toBeVisible();

  await page.getByText("SlideForge", { exact: true }).click();
  await page.getByText("Strict", { exact: true }).click();
  await page.getByRole("button", { name: /Set up template/ }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "strict.pptx",
    mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    buffer: Buffer.from("pptx"),
  });

  await expect(page.getByText("2 mapped slides")).toBeVisible();
  await expect(page.getByText("S1 · client_name")).toBeVisible();
  await expect(page.getByText("S2 · renewal_date")).toBeVisible();
});

test("mobile checkpoint and review surfaces do not overflow horizontally", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 820 });
  await mockPlanFlow(page);
  await page.goto("/");

  await page.getByRole("button", { name: /Start brief/ }).click();
  await expectNoHorizontalOverflow(page);

  await page.locator("textarea").fill("Make the case for structured AI-assisted coding.");
  await page.getByRole("button", { name: "Preview plan" }).click();
  await page.getByRole("button", { name: /Review plan/ }).last().click();
  await expect(page.getByRole("heading", { name: /Review the storyline/ })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("button", { name: /Render deck/ }).click();
  await page.getByRole("button", { name: /Review deck/ }).last().click();
  await expect(page.getByText("DECK INTELLIGENCE")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.locator(".sf-review-grid img").first().click();
  await expect(page.getByText("OUTLINE")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
