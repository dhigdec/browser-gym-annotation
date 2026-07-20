import { useState } from "react";
import { Button, Icon, Meter, Tag, t, weight, VERIFIER_LEVEL } from "../../../ds";
import type { VerifierLevel } from "../../../ds";
import type { ReviewState, Verifier } from "../../../lib/types";
import {
  allVerifiers,
  canSubmit,
  failingCount,
  levelScore,
  levelVerifiers,
  reward,
  verifierState,
} from "../../../lib/reviewMachine";
import { BenchmarkDock } from "./BenchmarkDock";

const LEVELS = Object.keys(VERIFIER_LEVEL) as VerifierLevel[];

function LevelChip({ level, muted }: { level: VerifierLevel; muted?: boolean }) {
  const L = VERIFIER_LEVEL[level];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 7, padding: "6px 12px", borderRadius: t.radiusPill, background: t.n85, border: `1px solid ${t.n7}`, fontSize: "0.8125rem", fontWeight: weight.semibold, color: muted ? t.n3 : t.n1 }}>
      <span style={{ width: 8, height: 8, borderRadius: t.radiusFull, background: L.color }} />
      {L.label}
    </span>
  );
}

function EmptyState({ unlocked, onGenerate }: { unlocked: boolean; onGenerate: () => void }) {
  return (
    <div style={{ padding: "48px 24px", display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center" }}>
      <span style={{ width: 52, height: 52, borderRadius: t.radiusXl, background: t.primary0, color: t.primary6, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
        <Icon name="checkSquare" size={26} color={t.primary6} />
      </span>
      <div style={{ marginTop: 16, fontSize: "1.1rem", fontWeight: weight.bold, color: t.n0 }}>
        {unlocked ? "Steps approved — ready to build verifiers" : "Approve the steps first"}
      </div>
      <div style={{ marginTop: 6, fontSize: "0.875rem", color: t.n2, maxWidth: 460, lineHeight: 1.5 }}>
        {unlocked
          ? "Generate a verifier suite. Each level gets multiple typed checks you can edit and extend before running the benchmark."
          : "Review and correct the agent run above, then approve all steps. The verifier suite unlocks once the trace is approved."}
      </div>
      <div style={{ margin: "22px 0", display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
        {LEVELS.map((lv) => (
          <LevelChip key={lv} level={lv} muted={!unlocked} />
        ))}
      </div>
      <Button disabled={!unlocked} onClick={onGenerate}>Generate verifier suite</Button>
    </div>
  );
}

function VerifierRow({ v, state, benchmarkRun, onOverride }: { v: Verifier; state: ReviewState; benchmarkRun: boolean; onOverride: (id: string) => void }) {
  const vs = verifierState(state, v);
  const meterState = benchmarkRun ? vs : "pending";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 18px", borderTop: `1px solid ${t.n7}` }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "0.875rem", fontWeight: weight.bold, color: t.n0 }}>{v.assertion}</div>
        <div style={{ marginTop: 3, fontFamily: t.fontMono, fontSize: "0.8125rem", color: t.n2, overflowX: "auto" }}>{v.code}</div>
      </div>
      {benchmarkRun && vs === "fail" && !state.overrides[v.id] && (
        <span onClick={() => onOverride(v.id)} style={{ fontSize: "0.75rem", fontWeight: weight.semibold, color: t.red, cursor: "pointer", whiteSpace: "nowrap" }}>Override</span>
      )}
      {benchmarkRun && state.overrides[v.id] && (
        <Tag tone="tinted" color={t.yellow} style={{ fontSize: "0.68rem" }}>overridden</Tag>
      )}
      <Meter state={meterState} />
      <Icon name="pencil" size={15} color={t.n3} style={{ cursor: "pointer" }} />
    </div>
  );
}

function AddEditor({ level, onCancel, onSave }: { level: VerifierLevel; onCancel: () => void; onSave: (assertion: string, code: string) => void }) {
  const [assertion, setAssertion] = useState("");
  const [code, setCode] = useState("assert /* define check */");
  const inputStyle = { width: "100%", padding: "9px 12px", borderRadius: t.radiusLg, border: `1px solid ${t.primary6}`, fontFamily: t.fontPrimary, fontSize: "0.875rem", color: t.n0, outline: "none", boxSizing: "border-box" as const };
  return (
    <div style={{ padding: "14px 18px", borderTop: `1px solid ${t.n7}`, display: "flex", flexDirection: "column", gap: 10 }}>
      <input value={assertion} placeholder="New verifier assertion" onChange={(e) => setAssertion(e.target.value)} style={inputStyle} />
      <textarea value={code} onChange={(e) => setCode(e.target.value)} rows={3} style={{ ...inputStyle, fontFamily: t.fontMono, background: t.n85, border: `1px solid ${t.n7}`, resize: "vertical" }} />
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button onClick={() => onSave(assertion || "New verifier assertion", code)}>Save</Button>
      </div>
      <div style={{ fontSize: "0.72rem", color: t.n3 }}>Level: {VERIFIER_LEVEL[level].label}. An empty or placeholder check scores 0 — never 1.</div>
    </div>
  );
}

export function VerifierSuite({
  state,
  onGenerate,
  onSetLevel,
  onAddVerifier,
  onOverride,
  onRun,
  onSubmit,
}: {
  state: ReviewState;
  onGenerate: () => void;
  onSetLevel: (l: VerifierLevel) => void;
  onAddVerifier: (assertion: string, code: string) => void;
  onOverride: (id: string) => void;
  onRun: () => void;
  onSubmit: () => void;
}) {
  const [adding, setAdding] = useState(false);

  const cardShell = { background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowMd, overflow: "hidden" } as const;

  if (!state.stepsApproved) return <div style={cardShell}><EmptyState unlocked={false} onGenerate={onGenerate} /></div>;
  if (!state.verifiersGenerated) return <div style={cardShell}><EmptyState unlocked onGenerate={onGenerate} /></div>;

  const L = VERIFIER_LEVEL[state.activeLevel];
  const group = levelVerifiers(state, state.activeLevel);
  const overridden = Object.keys(state.overrides).length > 0;

  return (
    <div style={cardShell}>
      {/* level tab bar */}
      <div style={{ display: "flex", gap: 26, padding: "0 20px", borderBottom: `1px solid ${t.n7}` }}>
        {LEVELS.map((lv) => {
          const active = lv === state.activeLevel;
          const sc = levelScore(state, lv);
          const V = VERIFIER_LEVEL[lv];
          return (
            <div key={lv} onClick={() => onSetLevel(lv)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 2px", cursor: "pointer", borderBottom: active ? `2px solid ${V.color}` : "2px solid transparent", marginBottom: -1 }}>
              <span style={{ width: 8, height: 8, borderRadius: t.radiusFull, background: V.color }} />
              <span style={{ fontSize: "0.875rem", fontWeight: weight.semibold, color: active ? t.n0 : t.n3 }}>{V.label}</span>
              <span style={{ fontFamily: t.fontMono, fontSize: "0.78rem", color: t.n3 }}>{state.benchmarkRun ? `${sc.pass} / ${sc.total}` : `${sc.total} checks`}</span>
            </div>
          );
        })}
      </div>

      {/* active group */}
      <div style={{ padding: 16 }}>
        <div style={{ border: `1px solid ${t.n7}`, borderRadius: t.radiusLg, overflow: "hidden" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", background: t.n85 }}>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 9, height: 9, borderRadius: t.radiusFull, background: L.color }} />
              <span style={{ fontSize: "0.9rem", fontWeight: weight.bold, color: t.n0 }}>{L.label}</span>
              <Tag tone="tinted" color={L.color}>{L.chip}</Tag>
            </span>
            <span style={{ fontFamily: t.fontMono, fontSize: "0.8125rem", color: t.n2 }}>{state.benchmarkRun ? `${levelScore(state, state.activeLevel).pass} / ${group.length}` : `${group.length} checks`}</span>
          </div>

          {group.map((v) => (
            <VerifierRow key={v.id} v={v} state={state} benchmarkRun={state.benchmarkRun} onOverride={onOverride} />
          ))}

          {adding ? (
            <AddEditor level={state.activeLevel} onCancel={() => setAdding(false)} onSave={(a, c) => { onAddVerifier(a, c); setAdding(false); }} />
          ) : (
            <div onClick={() => setAdding(true)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 18px", borderTop: `1px solid ${t.n7}`, color: t.primary6, fontSize: "0.8125rem", fontWeight: weight.semibold, cursor: "pointer" }}>
              <Icon name="plus" size={16} color={t.primary6} /> Add a verifier to {L.label}
            </div>
          )}
        </div>
      </div>

      <BenchmarkDock
        reward={reward(state)}
        benchmarkRun={state.benchmarkRun}
        failing={failingCount(state)}
        total={allVerifiers(state).length}
        overridden={overridden}
        canSubmit={canSubmit(state)}
        submitted={state.submitted}
        onRun={onRun}
        onSubmit={onSubmit}
      />
    </div>
  );
}
