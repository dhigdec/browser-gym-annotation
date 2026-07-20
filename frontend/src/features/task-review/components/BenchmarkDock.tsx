import { Button, Icon, Tag, t, weight } from "../../../ds";

export function BenchmarkDock({
  reward,
  benchmarkRun,
  failing,
  total,
  overridden,
  canSubmit,
  submitted,
  onRun,
  onSubmit,
}: {
  reward: number | null;
  benchmarkRun: boolean;
  failing: number;
  total: number;
  overridden: boolean;
  canSubmit: boolean;
  submitted: boolean;
  onRun: () => void;
  onSubmit: () => void;
}) {
  const numeralColor = reward == null ? t.n4 : reward === 1 ? t.greenDark : t.red;
  const numeral = reward == null ? "–" : String(reward);

  let sub: string;
  if (!benchmarkRun) sub = "Run the benchmark to score every verifier on the final state.";
  else if (reward === 1) sub = overridden ? `All checks resolved (with override) — safe to submit.` : `All ${total} verifiers passed. Ready to submit.`;
  else sub = `${failing} of ${total} verifiers scored 0. Override to submit, or edit a verifier / correct the trace and re-run.`;

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 20px", borderTop: `1px solid ${t.n7}`, background: t.n85 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span style={{ fontFamily: t.fontMono, fontSize: "2.375rem", fontWeight: weight.bold, lineHeight: 1, color: numeralColor, minWidth: 34, textAlign: "center" }}>{numeral}</span>
        <div>
          <div style={{ fontSize: "0.6875rem", fontWeight: weight.semibold, letterSpacing: "0.04em", color: t.n3, textTransform: "uppercase" }}>Benchmark reward</div>
          <div style={{ marginTop: 3, fontSize: "0.8125rem", color: t.n2, maxWidth: 560 }}>{sub}</div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {submitted ? (
          <Tag tone="tinted" color={t.green} style={{ padding: "8px 12px" }}>
            <Icon name="check" size={14} color={t.greenDark} style={{ marginRight: 6 }} /> Submitted to dataset · reward {reward}
          </Tag>
        ) : (
          <>
            <Button variant={benchmarkRun ? "secondary" : "primary"} onClick={onRun}>
              {benchmarkRun ? "Re-run benchmark" : "Run benchmark"}
            </Button>
            <Button variant="primary" disabled={!canSubmit} onClick={onSubmit}>
              Approve &amp; submit to dataset
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
