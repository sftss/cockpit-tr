import type { Report } from "./api";

/** Value of the whole broker portfolio, or null while a line has no price. */
export const accountTotal = (report: Report): number | null =>
  report.accounts.some((a) => a.open_lines > 0 && a.value == null)
    ? null
    : report.accounts.reduce((sum, a) => sum + (a.value ?? 0), 0);
