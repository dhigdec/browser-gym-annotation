import { Button, Icon, t, weight, ACTION_COLOR } from "../../../ds";
import type { Step, Tab } from "../../../lib/types";

function TabStrip({ tabs, activeId, onSelect }: { tabs: Tab[]; activeId: string; onSelect: (id: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, padding: "7px 8px 0", background: t.n8, borderBottom: `1px solid ${t.n7}` }}>
      {tabs.map((tab) => {
        const active = tab.id === activeId;
        return (
          <div
            key={tab.id}
            onClick={() => onSelect(tab.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              height: 32,
              padding: "0 12px",
              borderRadius: "8px 8px 0 0",
              cursor: "pointer",
              transition: t.transitionUi,
              background: active ? t.n9 : "transparent",
              borderTop: active ? `2px solid ${tab.color}` : "2px solid transparent",
              borderLeft: active ? `1px solid ${t.n7}` : "1px solid transparent",
              borderRight: active ? `1px solid ${t.n7}` : "1px solid transparent",
              color: active ? t.n0 : t.n3,
              marginBottom: active ? -1 : 0,
            }}
          >
            <span style={{ width: 8, height: 8, borderRadius: t.radiusFull, background: tab.color, flexShrink: 0 }} />
            <span style={{ fontSize: "0.78rem", fontWeight: weight.semibold, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{tab.title}</span>
            <Icon name="close" size={12} stroke={1.3} color={t.n3} style={{ opacity: 0.4 }} />
          </div>
        );
      })}
      <span style={{ width: 28, height: 30, display: "inline-flex", alignItems: "center", justifyContent: "center", color: t.n3, cursor: "pointer" }}>
        <Icon name="plus" size={15} stroke={1.7} />
      </span>
    </div>
  );
}

function UrlBar({ host }: { host: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "9px 14px", borderBottom: `1px solid ${t.n7}`, background: t.n9 }}>
      <div style={{ display: "flex", gap: 4, color: t.n3 }}>
        <Icon name="chevronLeft" size={17} />
        <Icon name="chevronRight" size={17} style={{ opacity: 0.4 }} />
        <Icon name="reload" size={16} />
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 12px", background: t.n85, border: `1px solid ${t.n7}`, borderRadius: t.radius2xl, fontSize: "0.8125rem", color: t.n1 }}>
        <Icon name="lock" size={13} color={t.green} />
        {host}
      </div>
    </div>
  );
}

/** Faithful-enough captured frame of the ShopGym checkout for the demo step. */
function ShopCheckoutFrame({ corrected }: { corrected: boolean }) {
  return (
    <div style={{ padding: 20 }}>
      {corrected ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: t.greenLite, color: t.greenDark, borderRadius: t.radiusLg, fontSize: "0.84rem", fontWeight: weight.semibold }}>
          <Icon name="check" size={16} color={t.greenDark} /> Paid with PayPal · order confirmed #SG8842
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", background: t.redLite, color: t.redDark, borderRadius: t.radiusLg, fontSize: "0.84rem", fontWeight: weight.semibold }}>
          Checkout blocked — your Visa was declined (card expired). Use another card or continue.
        </div>
      )}

      <div style={{ marginTop: 18, fontSize: "0.95rem", fontWeight: weight.bold, color: t.n0 }}>ShopGym · Review &amp; pay</div>
      <div style={{ marginTop: 4, fontSize: "0.8125rem", color: t.n2 }}>Wireless Keyboard + Mouse · deliver by May 22</div>

      <div style={{ marginTop: 16, border: `1px solid ${t.n7}`, borderRadius: t.radiusLg, overflow: "hidden" }}>
        {[
          { label: "Visa ····4242", note: corrected ? "expired" : "declined — expired", bad: true, sel: false },
          { label: "PayPal (alice@shopgym.com)", note: "personal", bad: false, sel: corrected },
          { label: "Corporate Amex ····1009", note: "not allowed for personal orders", bad: false, sel: !corrected },
        ].map((p, i) => (
          <div key={p.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderTop: i ? `1px solid ${t.n7}` : "none", background: p.sel ? t.surfaceTint : t.n9 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 15, height: 15, borderRadius: t.radiusFull, border: `2px solid ${p.sel ? t.primary6 : t.n5}`, background: p.sel ? t.primary6 : "transparent" }} />
              <span style={{ fontSize: "0.875rem", fontWeight: weight.semibold, color: t.n0 }}>{p.label}</span>
            </div>
            <span style={{ fontSize: "0.78rem", color: p.bad ? t.red : t.n3 }}>{p.note}</span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
        <span style={{ padding: "10px 20px", background: t.primary6, color: t.n9, borderRadius: t.radiusLg, fontSize: "0.875rem", fontWeight: weight.semibold }}>Place order →</span>
      </div>
    </div>
  );
}

function GenericFrame({ tab }: { tab: Tab }) {
  return (
    <div style={{ padding: 20, color: t.n3 }}>
      <div style={{ fontSize: "0.95rem", fontWeight: weight.bold, color: t.n1 }}>{tab.title}</div>
      <div style={{ marginTop: 8, height: 220, border: `1px dashed ${t.n6}`, borderRadius: t.radiusLg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8125rem" }}>
        Captured frame — {tab.host}
      </div>
    </div>
  );
}

function StepOverlay({ step, stepNumber, onVerify, onCorrect }: { step: Step; stepNumber: number; onVerify: () => void; onCorrect: () => void }) {
  const isError = step.type === "error";
  const color = ACTION_COLOR[step.type];
  return (
    <div style={{ position: "absolute", left: 16, right: 16, bottom: 14, display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", background: t.n9, border: `1px solid ${t.n7}`, borderLeft: `3px solid ${isError ? t.red : color}`, borderRadius: t.radiusLg, boxShadow: t.shadowLg }}>
      <span style={{ fontFamily: t.fontMono, fontSize: "0.7rem", fontWeight: weight.bold, letterSpacing: "0.03em", color: isError ? t.red : color, textTransform: "uppercase", whiteSpace: "nowrap" }}>
        Step {stepNumber} · {step.type}
      </span>
      <span style={{ flex: 1, fontSize: "0.875rem", fontWeight: weight.semibold, color: t.n0 }}>{step.description}</span>
      <Button variant="secondary" leading={<Icon name="check" size={15} />} onClick={onVerify}>Verify</Button>
      <Button variant="soft" leading={<Icon name="pencil" size={14} />} onClick={onCorrect}>Correct</Button>
    </div>
  );
}

export function ReplayPane({
  tabs,
  activeTabId,
  onSelectTab,
  step,
  stepNumber,
  corrected,
  onVerify,
  onCorrect,
}: {
  tabs: Tab[];
  activeTabId: string;
  onSelectTab: (id: string) => void;
  step: Step;
  stepNumber: number;
  corrected: boolean;
  onVerify: () => void;
  onCorrect: () => void;
}) {
  const activeTab = tabs.find((tb) => tb.id === activeTabId) ?? tabs[0];
  const showOverlay = step.tabId === activeTabId;
  return (
    <div style={{ flex: 1, minHeight: 0, background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowMd, overflow: "hidden", display: "flex", flexDirection: "column" }}>
      <TabStrip tabs={tabs} activeId={activeTabId} onSelect={onSelectTab} />
      <UrlBar host={activeTab.host} />
      <div style={{ position: "relative", flex: 1, minHeight: 0, overflow: "auto", background: t.n9 }}>
        <div style={{ padding: "8px 20px 0", fontSize: "0.72rem", color: t.n3 }}>Captured frame · rendered DOM snapshot</div>
        {activeTab.id === "shop" ? <ShopCheckoutFrame corrected={corrected} /> : <GenericFrame tab={activeTab} />}
        {showOverlay && <StepOverlay step={step} stepNumber={stepNumber} onVerify={onVerify} onCorrect={onCorrect} />}
      </div>
    </div>
  );
}
