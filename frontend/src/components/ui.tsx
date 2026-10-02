import type { ReactNode } from "react";
import { DASH } from "../format";

export function PageTitle({ children, lead }: { children: ReactNode; lead?: ReactNode }) {
  return (
    <header className="mb-8">
      <h1 className="font-display text-[28px] leading-tight">{children}</h1>
      {lead && <p className="mt-2 max-w-[70ch] text-muted">{lead}</p>}
    </header>
  );
}

export function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-12">
      <h2 className="font-display text-xl">{title}</h2>
      {note && <p className="mt-1 max-w-[75ch] text-sm text-muted">{note}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Tables scroll sideways on a narrow screen instead of squeezing the figures. */
export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto">{children}</div>;
}

/** A result: red when money was lost, plain ink otherwise. */
export function Result({ value, children }: { value: number | null; children: ReactNode }) {
  if (value == null) return <span className="text-muted">{DASH}</span>;
  return <span className={`num ${value < 0 ? "text-loss" : ""}`}>{children}</span>;
}

export function Button({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface hover:opacity-90 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error"; children: ReactNode }) {
  const style = tone === "error" ? "border-loss text-loss" : "border-accent";
  return <div className={`rounded-md border-l-4 bg-surface px-4 py-3 text-sm ${style}`}>{children}</div>;
}

/** A secondary action: outlined, never competing with the main button of a section. */
export function Quiet({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-accent px-3 py-1 text-sm text-accent hover:bg-accent-soft disabled:opacity-50"
    >
      {children}
    </button>
  );
}

export const inputClass = "rounded-md border border-line bg-surface px-2 py-1";

/** A labelled field: the label is always visible, never a placeholder. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <span className="mt-1 block">{children}</span>
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
