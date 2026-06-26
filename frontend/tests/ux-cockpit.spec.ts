import { expect, Page, test } from "@playwright/test";

const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAEtAI8Gz0XnQAAAABJRU5ErkJggg==",
  "base64"
);

const now = "2026-06-23T12:00:00Z";

function freeformJob(status: string, progress: number, id = "job-plan") {
  const rendered = status === "done" || status === "review_failed";
  return {
    id,
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
    qa_rounds: rendered ? 2 : 0,
    warnings: [],
    result_file: rendered ? "/tmp/output.pptx" : null,
    preview_dir: rendered ? "/tmp/preview" : null,
    error_message: status === "review_failed" ? "Deck generated but failed final review with 2 unresolved issue(s)." : null,
    created_at: now,
    completed_at: status === "queued" ? null : now,
  };
}

function planningSummary() {
  return {
    available: true,
    artifacts: ["source-compression", "story-map", "spec-gate", "editing-contract"],
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
    editing_contract: {
      standard: "claude-pptx-editing-v1",
      source: "https://github.com/anthropics/skills/blob/main/skills/pptx/editing.md",
      status: "pass",
      phase: "planned",
      issue_count: 0,
      requirement_count: 2,
      passed_requirement_count: 2,
      warning_requirement_count: 0,
      slide_count: 2,
      unique_layout_count: 2,
      unique_composition_family_count: 2,
      bullet_card_ratio: 0.5,
      composition_card_ratio: 0.25,
      diagram_count: 0,
      template_mapped_count: 0,
      slot_risk_count: 1,
      structural_operation_count: 2,
      structural_warning_count: 0,
      formatting_fix_count: 2,
      formatting_warning_count: 0,
      requirements: [
        {
          id: "varied_composition_families",
          label: "Vary visible composition families",
          status: "pass",
          message: "2 visible composition families used; target is at least 2.",
        },
        {
          id: "complete_structure_before_content_edit",
          label: "Complete structural plan before content edits",
          status: "pass",
          message: "2 structural operation(s) planned before content edits.",
        },
      ],
      warnings: [],
    },
  };
}

function visualReview(status = "pass") {
  const passed = status === "pass";
  return {
    status,
    preview_count: passed ? 1 : 0,
    expected_slide_count: 1,
    preview_coverage: passed,
    audit_available: passed,
    audit_slide_count: passed ? 1 : 0,
    audit_preview_match: passed,
    audit_passed: passed ? true : null,
    audit_issue_count: 0,
    audit_critical_count: 0,
    message: passed ? "Full-resolution previews and rendered-slide audit are complete." : "Full-resolution visual review runs after rendering.",
  };
}

function cloneEditSummary() {
  return {
    available: true,
    artifact: "template-clone-edit",
    status: "pass",
    slide_count: 2,
    mapping_count: 2,
    blocked_mapping_count: 0,
    weak_mapping_count: 0,
    edit_target_count: 5,
    rewritten_target_count: 4,
    deleted_target_count: 1,
    rewritten_table_cell_count: 3,
    deleted_table_row_count: 1,
    warning_count: 0,
  };
}

function blockedCloneEditSummary() {
  return {
    ...cloneEditSummary(),
    status: "blocked",
    slide_count: 1,
    mapping_count: 1,
    blocked_mapping_count: 1,
    weak_mapping_count: 1,
    edit_target_count: 0,
    rewritten_target_count: 0,
    deleted_target_count: 0,
    rewritten_table_cell_count: 0,
    deleted_table_row_count: 0,
    warning_count: 1,
  };
}

function editingContract() {
  return {
    artifact: "editing-contract",
    standard: "claude-pptx-editing-v1",
    status: "pass",
    issue_count: 0,
    slides: [
      {
        slide_index: 0,
        layout: "comparison_table",
        content_type: "structured_comparison",
        structural_operation: { operation: "use_template_frame" },
        formatting_plan: { status: "fixed", action: "sanitized_unicode_bullets" },
        slot_plan: { status: "cleanup", action: "delete_excess_template_elements" },
      },
      {
        slide_index: 1,
        layout: "chart",
        content_type: "evidence_points",
        structural_operation: { operation: "render_native_composition" },
        formatting_plan: { status: "pass", action: "inherit_layout_list_formatting" },
        slot_plan: { status: "native", action: "use_native_composition_slots" },
      },
    ],
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
      template_frame: {
        source_slide: 3,
        label: "Comparison frame",
        method: "semantic_match",
        content_category: "comparison",
        reuse_mode: "duplicate-slide-edit",
      },
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
  await page.route("**/api/jobs/job-plan/planning/editing-contract", (route) =>
    route.fulfill({ json: editingContract() })
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
        visual_review: renderRequested ? visualReview("pass") : visualReview("pending"),
        template_clone_edit: renderRequested ? cloneEditSummary() : { available: false, artifact: "template-clone-edit" },
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

async function mockReviewFailedFlow(page: Page) {
  const counters = { statusGets: 0 };

  await page.route("**/api/jobs/job-failed/planning/source-compression", (route) =>
    route.fulfill({ json: planningSummary().source_coverage })
  );
  await page.route("**/api/jobs/job-failed/planning/story-map", (route) =>
    route.fulfill({ json: { status: "ready", beats: [{ role: "setup", preferred_exhibit: "comparison_table" }] } })
  );
  await page.route("**/api/jobs/job-failed/planning/spec-gate", (route) =>
    route.fulfill({ json: planningSummary().spec_gate })
  );
  await page.route("**/api/jobs/job-failed/planning/editing-contract", (route) =>
    route.fulfill({ json: editingContract() })
  );
  await page.route("**/api/jobs/job-failed/qa/rendered-slide-audit", (route) =>
    route.fulfill({
      json: {
        passed: false,
        issue_count: 2,
        critical_count: 1,
        warning_count: 1,
        visual_rhythm: { slide_count: 1, unique_family_count: 1 },
        slides: [
          {
            slide_index: 0,
            text: ["Text is cut off."],
            paragraph_text: ["Text is cut off."],
            layout_diagnostics: {
              text_box_count: 8,
              opaque_shape_count: 2,
              overflow_risk_count: 1,
              overlap_pair_count: 1,
              occlusion_pair_count: 1,
              overflow_risks: [
                {
                  shape_index: 3,
                  text: "A long title may overflow the available title box.",
                  font_size: 24,
                  estimated_lines: 3,
                  capacity_lines: 2,
                },
              ],
              overlap_pairs: [
                {
                  shape_indexes: [3, 4],
                  overlap_ratio: 0.42,
                  texts: ["A long title may overflow", "Subtitle overlaps title"],
                },
              ],
              occlusion_pairs: [
                {
                  shape_indexes: [3, 7],
                  overlap_ratio: 0.31,
                  text: "A long title is covered by an opaque card.",
                },
              ],
            },
            issues: [
              { severity: "CRITICAL", message: "Text is cut off.", slide_index: 0, category: "cut-off-text" },
            ],
          },
        ],
      },
    })
  );
  await page.route("**/api/jobs/job-failed/outline", (route) => route.fulfill({ json: { slides: baseOutline() } }));
  await page.route("**/api/jobs/job-failed/preview/slide-001.jpg", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/jobs/job-failed", (route) => {
    counters.statusGets += 1;
    route.fulfill({
      json: {
        job: freeformJob("review_failed", 1, "job-failed"),
        warnings: [],
        preview_images: ["slide-001.jpg"],
        qa_summary: { critical: 1, warning: 1, info: 0, count: 2 },
        qa_issues: [{ severity: "CRITICAL", message: "Text is cut off.", slide_index: 0, category: "cut-off-text" }],
        qa_history: [
          {
            round: 2,
            passed: false,
            summary: { critical: 1, warning: 1, info: 0, count: 2 },
            actionable_issue_count: 2,
            stop_reason: "max_rounds",
          },
        ],
        planning_summary: planningSummary(),
        final_qa_passed: false,
        final_review_passed: false,
        unresolved_critical_count: 1,
        unresolved_actionable_issue_count: 2,
        unresolved_editing_contract_count: 1,
        rendered_slide_audit: {
          available: true,
          artifact: "rendered-slide-audit",
          path: "qa/rendered-slide-audit",
          passed: false,
          issue_count: 2,
          critical_count: 1,
          warning_count: 1,
          slide_count: 1,
          rhythm_slide_count: 1,
          unique_family_count: 1,
          card_like_ratio: 1,
          most_repeated_family: { family: "proof_strip", count: 1 },
          top_issues: [
            {
              severity: "CRITICAL",
              category: "cut-off-text",
              message: "Text is cut off.",
              slide_index: 0,
            },
          ],
        },
        template_clone_edit: blockedCloneEditSummary(),
        visual_review: {
          status: "warning",
          preview_count: 1,
          expected_slide_count: 1,
          preview_coverage: true,
          audit_available: true,
          audit_slide_count: 1,
          audit_preview_match: true,
          audit_passed: false,
          audit_issue_count: 2,
          audit_critical_count: 1,
          message: "Full-resolution preview coverage or rendered-slide audit needs review.",
        },
      },
    });
  });
  await page.route("**/api/jobs", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ json: freeformJob("queued", 0, "job-failed") });
      return;
    }
    await route.fulfill({ json: { jobs: [freeformJob("review_failed", 1, "job-failed")] } });
  });
  await page.route("**/api/templates", (route) => route.fulfill({ json: { templates: [] } }));

  return counters;
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
    route.fulfill({
      json: {
        template_id: "brand-template",
        thumbnails: ["slide-001.jpg"],
        logo_available: true,
        frame_map: templateFrameMap("brand-template"),
      },
    })
  );
  await page.route("**/api/templates/brand-template/thumbnail/slide-001.jpg", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/templates/brand-template/logo", (route) =>
    route.fulfill({ body: png, contentType: "image/png" })
  );
  await page.route("**/api/templates/strict-template/assets", (route) =>
    route.fulfill({
      json: {
        template_id: "strict-template",
        thumbnails: [],
        logo_available: false,
        frame_map: templateFrameMap("strict-template"),
      },
    })
  );
}

function templateFrameMap(templateId: string) {
  return {
    available: true,
    artifact: "template-frame-map",
    standard: "claude-pptx-editing-v1",
    slide_count: 2,
    schema_bearing_slide_count: templateId === "strict-template" ? 2 : 0,
    slot_count: 9,
    slides: [
      {
        slide_index: 0,
        label: "Executive cover",
        layout_name: "Title",
        mode: templateId === "strict-template" ? "strict" : "flexible",
        slot_count: 4,
        text_slot_count: 3,
        media_slot_count: 1,
        schema_field_count: templateId === "strict-template" ? 1 : 0,
        content_category: "section_or_cover",
        visual_guidance: "3 text slot(s): title, body, caption; 1 media slot(s)",
        text_inventory: "Client name and executive title placeholder",
      },
      {
        slide_index: 1,
        label: "Renewal dashboard",
        layout_name: "Dashboard",
        mode: templateId === "strict-template" ? "strict" : "flexible",
        slot_count: 5,
        text_slot_count: 4,
        media_slot_count: 1,
        schema_field_count: templateId === "strict-template" ? 1 : 0,
        content_category: "metric_chart",
        visual_guidance: "4 text slot(s): title, body, body, footer; 1 chart frame(s)",
        text_inventory: "Renewal date, status, and action placeholders",
      },
    ],
  };
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
  await expect(page.getByRole("heading", { name: /Review the storyline/ })).toBeVisible();
  await expect(page.getByText("Slot fit risks")).toBeVisible();
  await expect(page.getByText("Structural ops")).toBeVisible();
  await expect(page.getByText("Formatting fixes")).toBeVisible();
  await expect(page.getByText("Full-res QA")).toBeVisible();
  await expect(page.getByText(/structure: use_template_frame/)).toBeVisible();
  await expect(page.getByText(/format: sanitized_unicode_bullets/)).toBeVisible();
  await expect(page.getByText(/slot: delete_excess_template_elements/)).toBeVisible();
  const firstTitle = page.locator(".sf-plan-grid input").first();
  await expect(firstTitle).toHaveValue("Old action title");
  await firstTitle.fill("Edited action title earns trust");
  await page.getByRole("button", { name: /Save title edits/ }).click();
  await expect(firstTitle).toHaveValue("Edited action title earns trust");

  await page.getByRole("button", { name: /Render deck/ }).click();
  await expect(page.getByText("DECK INTELLIGENCE")).toBeVisible();
  await expect(page.getByText("Clone/edit")).toBeVisible();
  await expect(page.getByText("TITLE LADDER")).toBeVisible();
  await expect(page.getByText("Edited action title earns trust")).toBeVisible();
  await expect(page.getByText("QA ISSUES")).toBeVisible();

  await page.locator(".sf-review-grid img").first().click();
  await expect(page.getByText("OUTLINE")).toBeVisible();
  await expect(page.getByText(/Source frame/)).toBeVisible();
  await expect(page.getByText("sec-001")).toBeVisible();
  await expect(page.getByText("Explain why the current workflow needs a checkpoint.")).toBeVisible();
});

test("review failed jobs automatically open review and stop job polling", async ({ page }) => {
  const counters = await mockReviewFailedFlow(page);
  await page.goto("/");

  await page.getByRole("button", { name: /Start brief/ }).click();
  await page.locator("textarea").fill("Summarize the uploaded source for executives.");
  await page.getByRole("button", { name: "Generate deck" }).click();

  await expect(page.getByText("REVIEW REQUIRED")).toBeVisible();
  await expect(page.getByText("DECK INTELLIGENCE")).toBeVisible();
  await expect(page.getByText("1 critical / 2 actionable / 1 editing")).toBeVisible();
  await expect(page.getByText("Structural plan", { exact: true })).toBeVisible();
  await expect(page.getByText("EDITING CHECKLIST")).toBeVisible();
  await expect(page.getByText("Vary visible composition families")).toBeVisible();
  await expect(page.getByText("Complete structural plan before content edits")).toBeVisible();
  await expect(page.getByText(/structure use_template_frame/)).toBeVisible();
  await expect(page.getByText("Formatting fixes")).toBeVisible();
  await expect(page.getByText(/format sanitized_unicode_bullets/)).toBeVisible();
  await expect(page.getByText("Full-res QA")).toBeVisible();
  await expect(page.getByText(/1\/1 previews \/ 2 audit issues/)).toBeVisible();
  await expect(page.getByText("Composition rhythm")).toBeVisible();
  await expect(page.getByText(/1 families \/ proof_strip x1 \/ 100% cards/)).toBeVisible();
  await expect(page.getByText("AUDIT FINDINGS")).toBeVisible();
  await expect(page.getByText("Text is cut off.").first()).toBeVisible();
  await expect(page.getByText("Clone/edit")).toBeVisible();
  await expect(page.getByText(/1 mapped \/ 0 targets \/ 1 blocked \/ 1 weak/)).toBeVisible();
  await expect(page.getByText("Slot fit risks")).toBeVisible();
  await expect(page.getByText(/slot delete_excess_template_elements/)).toBeVisible();
  await page.locator(".sf-review-grid img").first().click();
  const lightbox = page.locator(".sf-lightbox-shell");
  await expect(lightbox.getByText("RENDERED AUDIT", { exact: true })).toBeVisible();
  await expect(lightbox.getByText("Cut-off risk")).toBeVisible();
  await expect(lightbox.getByText("Overlap pairs")).toBeVisible();
  await expect(lightbox.getByText("Covered text")).toBeVisible();
  const statusGetsAfterReview = counters.statusGets;
  await page.waitForTimeout(1700);
  expect(counters.statusGets).toBe(statusGetsAfterReview);
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
  await expect(page.getByText("Template frame map")).toBeVisible();
  await expect(page.getByText("Client name and executive title placeholder")).toBeVisible();

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
  await expect(page.getByText("9", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Renewal date, status, and action placeholders")).toBeVisible();
});

test("mobile checkpoint and review surfaces do not overflow horizontally", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 820 });
  await mockPlanFlow(page);
  await page.goto("/");

  await page.getByRole("button", { name: /Start brief/ }).click();
  await expectNoHorizontalOverflow(page);

  await page.locator("textarea").fill("Make the case for structured AI-assisted coding.");
  await page.getByRole("button", { name: "Preview plan" }).click();
  await expect(page.getByRole("heading", { name: /Review the storyline/ })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("button", { name: /Render deck/ }).click();
  await expect(page.getByText("DECK INTELLIGENCE")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.locator(".sf-review-grid img").first().click();
  await expect(page.getByText("OUTLINE")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
