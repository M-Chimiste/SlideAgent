import { JobStatus, JobWarning, QaIssue } from "./api/client";

export type UiIssue = {
  severity: "CRITICAL" | "WARNING" | "INFO";
  message: string;
  slide_index: number | null;
  category: string | null;
  source: "qa" | "pipeline";
};

function warningSeverity(warning: JobWarning): UiIssue["severity"] {
  const severity = warning.severity?.toUpperCase();
  return severity === "CRITICAL" || severity === "INFO" ? severity : "WARNING";
}

function fromQaIssue(issue: QaIssue): UiIssue {
  return {
    severity: issue.severity,
    message: issue.message,
    slide_index: issue.slide_index ?? null,
    category: issue.category ?? null,
    source: "qa",
  };
}

function fromWarning(warning: JobWarning): UiIssue {
  return {
    severity: warningSeverity(warning),
    message: warning.message,
    slide_index: Number.isFinite(Number(warning.slide_index))
      ? Number(warning.slide_index)
      : null,
    category: warning.field || null,
    source: "pipeline",
  };
}

export function allIssues(status: JobStatus): UiIssue[] {
  return [
    ...(status.qa_issues ?? []).map(fromQaIssue),
    ...(status.warnings ?? []).map(fromWarning),
  ];
}

export function slideIssues(status: JobStatus, slideIndex: number): UiIssue[] {
  return allIssues(status).filter((issue) => issue.slide_index === slideIndex);
}

export function slidesWithIssues(status: JobStatus): Set<number> {
  return new Set(
    allIssues(status)
      .map((issue) => issue.slide_index)
      .filter((slideIndex): slideIndex is number => slideIndex != null)
  );
}

export function issueCounts(status: JobStatus): { critical: number; warning: number; info: number; count: number } {
  const issues = allIssues(status);
  return {
    critical: issues.filter((issue) => issue.severity === "CRITICAL").length,
    warning: issues.filter((issue) => issue.severity === "WARNING").length,
    info: issues.filter((issue) => issue.severity === "INFO").length,
    count: issues.length,
  };
}
