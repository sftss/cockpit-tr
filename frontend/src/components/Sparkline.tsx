import { euro } from "../format";

const W = 96;
const H = 28;
const PAD = 3;

/**
 * Last daily prices of one line, without axes: the shape is the message.
 * One neutral colour, since the result column already says gain or loss.
 */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return <span className="text-muted">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => PAD + (i * (W - 2 * PAD)) / (values.length - 1);
  const y = (v: number) => H - PAD - ((v - min) * (H - 2 * PAD)) / span;
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const last = values[values.length - 1];
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`${label}, ${values.length} derniers jours de cours : de ${euro(values[0])} à ${euro(last)}`}
      className="inline-block align-middle"
    >
      <path d={path} fill="none" stroke="var(--muted)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x(values.length - 1)} cy={y(last)} r="2.5" fill="var(--accent)" />
    </svg>
  );
}
