import { Button, Icon, t, weight } from "../../../ds";

export function BenchmarkDock({
  reward,
  benchmarkRun,
  failing,
  total,
  canSubmit,
  submitted,
  onRun,
  onSubmit,
}: {
  reward: number | null;
  benchmarkRun: boolean;
  failing: number;
  total: number;
  canSubmit: boolean;
  submitted: boolean;
  onRun: () => void;
  onSubmit: () => void;
}) {
  const numeralColor = reward == null ? t.n4 : reward === 1 ? t.greenDark : t.redDark;
  const numeral = reward == null ? "—" : String(reward);

  let sub: string;
  if (!benchmarkRun) sub = "Run the benchmark to score every verifier on the final state.";
  else if (reward === 1)
    sub = failing === 0
      ? `All ${total} verifiers scored 1 — ready to submit.`
      : `Reward 1 — ready to submit (${failing} non-required check${failing > 1 ? "s" : ""} did not fire).`;
  else sub = `${failing} of ${total} verifiers scored 0. Override to submit, or edit a verifier / correct the trace and re-run.`;

  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, padding: "16px 22px", borderTop: `1px solid ${t.n7}`, background: t.n85 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span style={{ fontFamily: t.fontMono, fontSize: "2.375rem", fontWeight: weight.bold, lineHeight: 1, color: numeralColor, minWidth: 38, textAlign: "center" }}>{numeral}</span>
        <div>
          <div style={{ fontSize: "0.6875rem", fontWeight: weight.bold, letterSpacing: "0.07em", color: t.n2, textTransform: "uppercase" }}>Benchmark reward</div>
          <div style={{ marginTop: 2, fontSize: "0.78rem", lineHeight: 1.45, color: t.n2, maxWidth: 560 }}>{sub}</div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {submitted ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 16px", borderRadius: 8, background: t.greenLite, color: t.greenDark, fontSize: "0.84rem", fontWeight: weight.bold }}>
            <Icon name="check" size={15} stroke={2.4} color={t.greenDark} /> Submitted to dataset · reward {reward}
          </span>
        ) : (
          <>
            <Button variant={benchmarkRun ? "secondary" : "primary"} onClick={onRun} style={{ minHeight: 44 }}>
              {benchmarkRun ? "Re-run benchmark" : "Run benchmark"}
            </Button>
            <Button variant="primary" disabled={!canSubmit} onClick={onSubmit} style={{ minHeight: 44 }}>
              Approve &amp; submit to dataset
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
