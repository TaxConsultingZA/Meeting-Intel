"use client";
import { useEffect, useRef, useState } from "react";
import { meetingInsights, type InsightDraft, type InsightCandidate } from "@/lib/api";
export default function MeetingInsights({ meetingId, token, canEdit }: { meetingId: string; token: string; canEdit: boolean }) {
  const [draft, setDraft] = useState<InsightDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const [confirmed, setConfirmed] = useState(() => new Set<string>());
  function remember(d: InsightDraft | null) { setConfirmed(new Set(d ? (["actions", "decisions"] as const).flatMap(k => d[k].flatMap((i, n) => i.status === "confirmed" ? [`${k}:${n}`] : [])) : [])); return d; }
  useEffect(() => { let active = true;
    meetingInsights(meetingId, token).then(d => { if (active) { setDraft(remember(d)); setLoaded(true); } })
      .catch(() => { if (active) setError("Unable to load analysis. Reload to retry."); });
    return () => { active = false; };
  }, [meetingId, token]);
  async function run(method: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try { setDraft(remember(await meetingInsights(meetingId, token, method, method === "PUT" && draft ? draft : undefined))); setDirty(false); }
    catch { setError("Could not save or generate. Your edits are retained. Reload if another reviewer or transcript changed."); }
    finally { lock.current = false; setBusy(false); }
  }
  function edit(kind: "actions" | "decisions", index: number, patch: Partial<InsightCandidate>) {
    if (!draft) return;
    setDraft({ ...draft, [kind]: draft[kind].map((item, n) => n === index ? { ...item, ...patch } : item) }); setDirty(true);
  }
  return <section className="rounded-xl border p-5 space-y-4" aria-label="Meeting analysis">
    <h2 className="text-lg font-semibold">Meeting analysis · Mock</h2>
    <p className="text-sm text-muted-foreground">Saved transcript only · Separate review draft · Unknown fields: 待确认</p>
    {error && <p role="alert">{error}</p>}
    {!loaded && !error && <p>Loading analysis…</p>}
    {loaded && !draft && <p>No analysis draft yet.</p>}
    {canEdit && loaded && (!draft || draft.status === "failed") && <button disabled={busy} onClick={() => run("POST")}>{busy ? "Analyzing…" : "Analyze saved transcript (mock)"}</button>}
    {draft && <>
      <p>Analysis: {draft.status} · Version {draft.version}</p>
      {draft.status === "failed" ? <p>Analysis failed. Saved transcript is intact. Retry available.</p> : <>
        <label className="block">Summary<textarea className="block w-full border rounded p-2" aria-label="Analysis summary" value={draft.summary} disabled={!canEdit || busy} onChange={e => { setDraft({ ...draft, summary: e.target.value }); setDirty(true); }} /></label>
        {(["actions", "decisions"] as const).map(kind => <div key={kind} className="space-y-3"><h3 className="font-semibold">{kind === "actions" ? "Action candidates" : "Decision candidates"}</h3>
          {!draft[kind].length && <p>No candidates.</p>}
          {draft[kind].map((item, index) => <fieldset key={index} disabled={!canEdit || busy || confirmed.has(`${kind}:${index}`)} className="border rounded p-3 space-y-2">
            <label className="block">Candidate<textarea className="block w-full border p-2" value={item.text} onChange={e => edit(kind, index, { text: e.target.value })} /></label>
            <blockquote className="border-l-2 pl-3 text-sm">Source: {item.source_quote}</blockquote>
            {kind === "actions" && <><label className="block">Owner<input className="border ml-2" placeholder="待确认" value={item.owner ?? ""} onChange={e => edit(kind, index, { owner: e.target.value || null })} /></label>
            <label className="block">Deadline<input className="border ml-2" placeholder="待确认" value={item.deadline ?? ""} onChange={e => edit(kind, index, { deadline: e.target.value || null })} /></label></>}
            <label>Review status <select value={item.status} onChange={e => edit(kind, index, { status: e.target.value as InsightCandidate["status"] })}>
              <option value="pending_confirmation">待确认</option><option value="confirmed">Confirmed</option><option value="rejected">Rejected</option>
            </select></label>
          </fieldset>)}
        </div>)}
        {canEdit && <><p className="text-sm">Saving confirmed action candidates adds them to reviewed actions. Confirmed candidates are locked.</p><button disabled={busy || !dirty} onClick={() => run("PUT")}>{busy ? "Saving…" : "Save review and confirmations"}</button></>}
      </>}
    </>}
  </section>;
}
