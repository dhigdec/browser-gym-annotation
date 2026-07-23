import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Icon, t, tint, weight } from "../../ds";
import {
  buildLineage,
  createFork,
  ensureBaseline,
  fetchVersionGraph,
  headOf,
  KIND_LABEL,
  runsLeft,
  selectHeadOrReload,
  setStatusOrReload,
  type ForkPoint,
  type RunsData,
  type VersionGraphData,
  type VersionNode,
  type VersionStatus,
} from "../../lib/versionsApi";

/**
 * The attempt's lineage: v1 canonical run → corrections → human edits.
 *
 * Two different things are true of a row and the design keeps them apart on
 * purpose: HEAD is the attempt's answer, VIEWING is just what the annotator is
 * reading. A finished agent run lands here as a candidate and stays one until
 * somebody selects it.
 */

const STATUS_TONE: Record<VersionStatus, { fg: string; label: string }> = {
  candidate: { fg: t.n2, label: "candidate" },
  approved: { fg: t.greenDark, label: "approved" },
  rejected: { fg: t.redDark, label: "rejected" },
  published: { fg: t.primary6, label: "published" },
};

function StatusChip({ status }: { status: VersionStatus }) {
  const tone = STATUS_TONE[status] ?? STATUS_TONE.candidate;
  return (
    <span
      style={{
        fontSize: "0.594rem",
        fontWeight: weight.bold,
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        color: tone.fg,
        background: tint(tone.fg, 12),
        padding: "2px 6px",
        borderRadius: t.radiusSm,
        whiteSpace: "nowrap",
      }}
    >
      {tone.label}
    </span>
  );
}

function Pill({ children, onClick, disabled, tone = t.primary6 }: { children: ReactNode; onClick: () => void; disabled?: boolean; tone?: string }) {
  return (
    <span
      onClick={disabled ? undefined : onClick}
      style={{
        padding: "4px 10px",
        borderRadius: t.radiusLg,
        border: `1px solid ${t.n6}`,
        background: t.n9,
        color: tone,
        fontSize: "0.719rem",
        fontWeight: weight.semibold,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** The banner a lost compare-and-swap produces. It is not an error toast: the
 *  write did not happen, the lineage below has already been re-read, and the
 *  annotator has to look again before deciding. */
function MovedOnNotice({ notice, onDismiss }: { notice: string; onDismiss: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 8,
        padding: "10px 14px",
        background: tint(t.yellow, 14),
        borderBottom: `1px solid ${t.n7}`,
      }}
    >
      <Icon name="alert" size={14} color={t.yellowDark} style={{ flexShrink: 0, marginTop: 1 }} />
      <span style={{ flex: 1, fontSize: "0.719rem", lineHeight: 1.45, color: t.n1, fontWeight: weight.medium }}>{notice}</span>
      <span onClick={onDismiss} style={{ cursor: "pointer", flexShrink: 0, marginTop: 1 }}>
        <Icon name="close" size={13} color={t.n3} />
      </span>
    </div>
  );
}

export function VersionGraph({
  graph,
  runs,
  viewingId,
  notice,
  busyVersionId,
  onView,
  onSelectHead,
  onSetStatus,
  onDismissNotice,
  onCreateBaseline,
}: {
  graph: VersionGraphData | null;
  runs?: RunsData | null;
  viewingId: string | null;
  notice: string | null;
  busyVersionId?: string | null;
  onView: (versionId: string) => void;
  onSelectHead: (v: VersionNode) => void;
  onSetStatus: (v: VersionNode, status: VersionStatus) => void;
  onDismissNotice: () => void;
  onCreateBaseline?: () => void;
}) {
  const rows = graph ? buildLineage(graph.versions) : [];
  const head = headOf(graph);
  const left = runsLeft(runs ?? null);
  // The payload carries the fork POINT but not the fork MODE, so a row can name
  // the version it branched from and must not claim which step it rejected.
  const numberOf = new Map((graph?.versions ?? []).map((v) => [v.id, v.versionNo]));

  return (
    <div style={{ background: t.n9, border: `1px solid ${t.n7}`, borderRadius: t.radiusXl, boxShadow: t.shadowMd, overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "12px 16px", borderBottom: `1px solid ${t.n7}` }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: "0.8125rem", fontWeight: weight.bold, color: t.n1 }}>
          <Icon name="branch" size={14} color={t.n3} /> Version lineage
        </span>
        <span style={{ fontFamily: t.fontMono, fontSize: "0.6875rem", color: t.n3 }}>
          {head ? `head v${head.versionNo}` : "no head yet"}
          {left != null ? ` · ${left} agent ${left === 1 ? "run" : "runs"} left` : ""}
        </span>
      </div>

      {notice && <MovedOnNotice notice={notice} onDismiss={onDismissNotice} />}

      {rows.length === 0 ? (
        <div style={{ padding: "18px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
          <span style={{ fontSize: "0.75rem", color: t.n2, lineHeight: 1.5 }}>
            No lineage yet. v1 is the canonical agent run this attempt annotates; every correction hangs off it.
          </span>
          {onCreateBaseline && (
            <Button variant="secondary" onClick={onCreateBaseline}>
              Create baseline v1
            </Button>
          )}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {rows.map(({ version: v, depth }) => {
            const viewing = v.id === viewingId;
            const busy = busyVersionId === v.id;
            return (
              <div
                key={v.id}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "11px 16px 11px 12px",
                  borderTop: `1px solid ${t.n8}`,
                  // HEAD is the loud one. Viewing only gets a tint, so "I am
                  // reading v3" can never be mistaken for "v3 is the answer".
                  background: v.isHead ? tint(t.primary6, 7) : viewing ? t.surfaceTint : "transparent",
                  borderLeft: `3px solid ${v.isHead ? t.primary6 : "transparent"}`,
                }}
              >
                {depth > 0 && (
                  <span aria-hidden style={{ width: depth * 12, flexShrink: 0, display: "flex", justifyContent: "flex-end", paddingTop: 8 }}>
                    <span style={{ width: 9, height: 9, borderLeft: `1px solid ${t.n6}`, borderBottom: `1px solid ${t.n6}`, borderBottomLeftRadius: t.radiusSm }} />
                  </span>
                )}

                <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                    <span
                      onClick={() => onView(v.id)}
                      style={{ fontFamily: t.fontMono, fontSize: "0.8125rem", fontWeight: weight.bold, color: viewing ? t.primary6 : t.n0, cursor: "pointer" }}
                    >
                      v{v.versionNo}
                    </span>
                    <span style={{ fontSize: "0.719rem", color: t.n2 }}>{KIND_LABEL[v.kind] ?? v.kind}</span>
                    {v.isHead && (
                      <span
                        style={{
                          fontSize: "0.594rem",
                          fontWeight: weight.black,
                          letterSpacing: "0.06em",
                          color: t.n9,
                          background: t.primary6,
                          padding: "2px 7px",
                          borderRadius: t.radiusSm,
                        }}
                      >
                        HEAD
                      </span>
                    )}
                    <StatusChip status={v.status} />
                    {viewing && !v.isHead && (
                      <span style={{ fontSize: "0.594rem", fontWeight: weight.bold, textTransform: "uppercase", letterSpacing: "0.04em", color: t.n3 }}>viewing</span>
                    )}
                  </div>

                  <span style={{ fontSize: "0.6875rem", color: t.n3, fontFamily: t.fontMono }}>
                    {v.stepCount} {v.stepCount === 1 ? "step" : "steps"}
                    {v.parentId && numberOf.has(v.parentId) ? ` · from v${numberOf.get(v.parentId)}` : ""}
                    {v.producer ? ` · ${v.producer}` : ""}
                  </span>

                  <span style={{ fontSize: "0.6875rem", lineHeight: 1.45, color: v.isHead ? t.primary6 : t.n2 }}>
                    {v.isHead
                      ? "The attempt's current answer."
                      : "Candidate — it is not the answer until you select it."}
                  </span>

                  {/* QC status is offered on the head too: finalize refuses to
                      ship a version that is not approved, and the head is the
                      one an annotator will try to ship. */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
                    {!v.isHead && (
                      <Pill onClick={() => onSelectHead(v)} disabled={busy}>
                        {busy ? "Selecting…" : `Make v${v.versionNo} the head`}
                      </Pill>
                    )}
                    {v.status !== "approved" && (
                      <Pill tone={t.greenDark} onClick={() => onSetStatus(v, "approved")} disabled={busy}>
                        Approve
                      </Pill>
                    )}
                    {v.status !== "rejected" && (
                      <Pill tone={t.redDark} onClick={() => onSetStatus(v, "rejected")} disabled={busy}>
                        Reject
                      </Pill>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ padding: "9px 16px", borderTop: `1px solid ${t.n8}`, background: t.n85 }}>
        <span style={{ fontSize: "0.6875rem", color: t.n3, lineHeight: 1.45 }}>
          Opening a version only reads it. An agent run finishes as a candidate and never takes the head on its own.
        </span>
      </div>
    </div>
  );
}

/**
 * Owns the lineage for one attempt: the graph, which version is being read, and
 * every compare-and-swap against it.
 *
 * `graph.revision` is the ATTEMPT's revision and guards head selection;
 * `version.revision` is per-version and guards a QC status change. They are
 * separate counters — passing one where the other belongs would make every
 * second call 409 for no reason.
 */
export function useVersionGraph(sessionId: string | null) {
  const [graph, setGraph] = useState<VersionGraphData | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyVersionId, setBusyVersionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // A refresh must not yank the annotator to another version mid-read: keep
  // what they were looking at, and only fall back to head when it is gone.
  const adopt = useCallback((g: VersionGraphData) => {
    setGraph(g);
    setViewingId((cur) => (cur && g.versions.some((v) => v.id === cur) ? cur : g.headVersionId ?? g.versions[g.versions.length - 1]?.id ?? null));
  }, []);

  const refresh = useCallback(async () => {
    if (!sessionId) return null;
    setLoading(true);
    const res = await fetchVersionGraph(sessionId);
    setLoading(false);
    if (!res.ok) {
      // Offline is already a first-class state everywhere else in this app —
      // degrade quietly rather than shouting at an annotator with no backend.
      if (res.kind !== "offline") setNotice(res.message);
      return null;
    }
    adopt(res.value);
    return res.value;
  }, [sessionId, adopt]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectHead = useCallback(
    async (v: VersionNode) => {
      if (!sessionId || !graph) return;
      setBusyVersionId(v.id);
      const out = await selectHeadOrReload(sessionId, v.id, graph.revision);
      if (out.reloaded) adopt(out.reloaded);
      else if (out.ok) await refresh();
      setNotice(out.notice);
      setBusyVersionId(null);
    },
    [sessionId, graph, adopt, refresh],
  );

  const setStatus = useCallback(
    async (v: VersionNode, status: VersionStatus) => {
      if (!sessionId) return;
      setBusyVersionId(v.id);
      const out = await setStatusOrReload(sessionId, v.id, status, v.revision);
      if (out.reloaded) adopt(out.reloaded);
      else if (out.ok) await refresh();
      setNotice(out.notice);
      setBusyVersionId(null);
    },
    [sessionId, adopt, refresh],
  );

  /** Branch. The child is opened for reading — deliberately NOT made head. */
  const fork = useCallback(
    async (point: ForkPoint) => {
      if (!sessionId) return null;
      const res = await createFork(sessionId, point);
      if (!res.ok) {
        setNotice(res.message);
        return null;
      }
      await refresh();
      setViewingId(res.value.id);
      return res.value;
    },
    [sessionId, refresh],
  );

  const baseline = useCallback(async () => {
    if (!sessionId) return;
    const res = await ensureBaseline(sessionId);
    if (!res.ok) setNotice(res.message);
    await refresh();
  }, [sessionId, refresh]);

  return {
    graph,
    viewingId,
    notice,
    loading,
    busyVersionId,
    head: headOf(graph),
    view: setViewingId,
    refresh,
    selectHead,
    setStatus,
    fork,
    baseline,
    dismissNotice: () => setNotice(null),
  };
}
