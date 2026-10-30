"use client";
import { useEffect, useRef, useState } from "react";
import { getRecordingUpdateStatus, runRecordingUpdateStage, type RecordingUpdateResult, type RecordingUpdateStage } from "@/lib/api";
import LocalDateTime from "./local-date-time";

const stages: RecordingUpdateStage[] = ["calendar","discovery","matching"];
const labels = {calendar:"Calendar sync",discovery:"Recording discovery",matching:"Automatic matching"};
const statuses = {never:"Not run yet",success:"Complete",partial:"Partially complete",failed:"Failed"};

export default function MeetingRecordingUpdate({token,onUpdated}:{token:string;onUpdated:()=>Promise<void>}) {
  const [results,setResults] = useState<RecordingUpdateResult[]>([]);
  const [current,setCurrent] = useState<RecordingUpdateStage | "refresh" | null>(null);
  const [refreshError,setRefreshError] = useState("");
  const [noticeOpen,setNoticeOpen] = useState(false);
  const inFlight = useRef(false);
  const version = useRef(0);
  useEffect(()=>{
    let active=true;
    const initialVersion=version.current;
    void getRecordingUpdateStatus(token).then(data=>{if(active && initialVersion===version.current)setResults(data);}).catch(()=>{
      if(active && initialVersion===version.current)setRefreshError("We couldn't load the previous update results. Try viewing them again.");
    });
    return ()=>{active=false;};
  },[token]);
  useEffect(()=>{
    if(!noticeOpen || current)return;
    const timer=window.setTimeout(()=>setNoticeOpen(false),60_000);
    return ()=>window.clearTimeout(timer);
  },[noticeOpen,current,results,refreshError]);
  const needsAttention=Boolean(refreshError) || results.some(r=>r.status==="failed" || r.status==="partial");
  async function viewResults() {
    setNoticeOpen(true);
    // This reads saved status only. It never resumes discovery or matching.
    if(results.length || !refreshError)return;
    try {setResults(await getRecordingUpdateStatus(token));setRefreshError("");}
    catch {setRefreshError("We couldn't load the previous update results. Please check your connection and try again.");}
  }
  async function update() {
    if(inFlight.current)return;
    inFlight.current=true; ++version.current; setRefreshError("");setNoticeOpen(true);
    try {
      for(const stage of stages) {
        setCurrent(stage);
        let result:RecordingUpdateResult;
        try { result=await runRecordingUpdateStage(token,stage); }
        catch { result={stage,status:"failed",counts:{},error:"This step couldn't finish. Check your connection, then try the update again.",last_attempted_at:new Date().toISOString(),last_succeeded_at:results.find(r=>r.stage===stage)?.last_succeeded_at || null}; }
        setResults(previous=>[...previous.filter(r=>r.stage!==stage),result]);
      }
      setCurrent("refresh");
      try { await onUpdated(); } catch { setRefreshError("The update finished, but we couldn't refresh the list. Please reload the page."); }
    } finally {setCurrent(null);inFlight.current=false;}
  }
  return <div className="inline-flex items-center gap-2">
    <button type="button" onClick={()=>void update()} disabled={current!==null}
      className="inline-flex min-h-10 items-center rounded-md border border-[#003366] bg-white px-3 py-2 text-[13px] font-semibold text-[#003366] disabled:opacity-50">
      {current ? "Updating…" : "Update meetings and recordings"}
    </button>
    {(results.length>0 || refreshError) && <button type="button" onClick={()=>void viewResults()}
      className="inline-flex min-h-10 items-center rounded-md px-2 text-xs font-semibold text-[#003366] hover:bg-blue-50"
      aria-label={needsAttention ? "View update results — needs attention" : "View update results"}>
      View update results{needsAttention && <span className="ml-1 text-amber-700" aria-hidden="true">!</span>}
    </button>}
    {noticeOpen && <section role="region" aria-label="Meeting and recording update results"
      className="fixed bottom-5 right-5 z-[60] max-h-[80vh] w-[min(26rem,calc(100vw-2.5rem))] overflow-auto rounded-lg border border-slate-200 bg-white p-4 text-left shadow-lg">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div><h2 className="text-sm font-semibold text-[#003366]">Meeting and recording update</h2>
          <p role="status" className="mt-1 text-xs text-slate-600">{current ? (current==="refresh" ? "Refreshing the list…" : labels[current]+" in progress…") : needsAttention ? "Some steps need attention. Saved results are retained." : results.some(r=>r.status!=="never") ? "Update complete." : "No updates have been run yet."}</p></div>
        <button type="button" aria-label="Dismiss update notification" onClick={()=>setNoticeOpen(false)}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-lg text-slate-600 hover:bg-slate-100">×</button>
      </div>
      <div aria-live="polite" className="space-y-3 text-xs text-[#4b5563]">
      {stages.map(stage=>{
        const r=results.find(item=>item.stage===stage);
        if(!r)return null;
        const counts=r.counts;
        return <div key={stage}>
          <span className="font-semibold">{labels[stage]}: {current===stage ? "In progress" : statuses[r.status]}</span>
          {stage==="calendar" && counts.events!==undefined && <span> · {counts.events} events</span>}
          {stage==="discovery" && counts.new!==undefined && <span> · {counts.new} new · {counts.changed} updated</span>}
          {stage==="matching" && counts.unresolved!==undefined && <span> · {counts.linked} matched · {counts.unresolved} unmatched</span>}
          {stage==="matching" && Boolean(counts.active_skipped) && <span> · {counts.active_skipped} active skipped</span>}
          <span className="mt-1 block text-slate-500">Last successful update: <LocalDateTime value={r.last_succeeded_at} unavailable="No successful update yet" /></span>
          {r.error && <span className="block text-amber-800">{r.error}</span>}
        </div>;
      })}
      {refreshError && <p role="alert">{refreshError}</p>}
      {!current && <p className="border-t pt-2 text-slate-500">This notification closes after about a minute. You can reopen it using View update results.</p>}
      </div>
    </section>}
  </div>;
}
