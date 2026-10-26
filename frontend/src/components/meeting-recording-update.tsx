"use client";
import { useEffect, useRef, useState } from "react";
import { getRecordingUpdateStatus, runRecordingUpdateStage, type RecordingUpdateResult, type RecordingUpdateStage } from "@/lib/api";
import LocalDateTime from "./local-date-time";

const stages: RecordingUpdateStage[] = ["calendar","discovery","matching"];
const labels = {calendar:"日历同步",discovery:"增量发现录音",matching:"自动匹配"};
const statuses = {never:"尚未运行",success:"成功",partial:"部分完成",failed:"失败"};

export default function MeetingRecordingUpdate({token,onUpdated}:{token:string;onUpdated:()=>Promise<void>}) {
  const [results,setResults] = useState<RecordingUpdateResult[]>([]);
  const [current,setCurrent] = useState<RecordingUpdateStage | "refresh" | null>(null);
  const [refreshError,setRefreshError] = useState("");
  const inFlight = useRef(false);
  const version = useRef(0);
  useEffect(()=>{
    let active=true;
    const initialVersion=version.current;
    void getRecordingUpdateStatus(token).then(data=>{if(active && initialVersion===version.current)setResults(data);}).catch(()=>{
      if(active && initialVersion===version.current)setRefreshError("无法读取上次更新结果；可重新更新。");
    });
    return ()=>{active=false;};
  },[token]);
  async function update() {
    if(inFlight.current)return;
    inFlight.current=true; ++version.current; setRefreshError("");
    try {
      for(const stage of stages) {
        setCurrent(stage);
        let result:RecordingUpdateResult;
        try { result=await runRecordingUpdateStage(token,stage); }
        catch { result={stage,status:"failed",counts:{},error:"此步骤未完成，请检查连接后重试。",last_attempted_at:new Date().toISOString(),last_succeeded_at:results.find(r=>r.stage===stage)?.last_succeeded_at || null}; }
        setResults(previous=>[...previous.filter(r=>r.stage!==stage),result]);
      }
      setCurrent("refresh");
      try { await onUpdated(); } catch { setRefreshError("更新已执行，但列表刷新失败。请刷新页面。"); }
    } finally {setCurrent(null);inFlight.current=false;}
  }
  return <div className="space-y-2">
    <button type="button" onClick={()=>void update()} disabled={current!==null}
      className="inline-flex min-h-10 items-center rounded-md border border-[#003366] bg-white px-3 py-2 text-[13px] font-semibold text-[#003366] disabled:opacity-50">
      {current ? (current==="refresh" ? "刷新列表…" : labels[current]+"…") : "更新会议和录音"}
    </button>
    <div aria-live="polite" className="space-y-1 text-left text-xs text-[#4b5563]">
      {stages.map(stage=>{
        const r=results.find(item=>item.stage===stage);
        if(!r)return null;
        const counts=r.counts;
        return <div key={stage}>
          <span>{labels[stage]}：{current===stage ? "进行中" : statuses[r.status]}</span>
          {stage==="calendar" && counts.events!==undefined && <span> · {counts.events} 个事件</span>}
          {stage==="discovery" && counts.new!==undefined && <span> · 新增 {counts.new} · 更新 {counts.changed}</span>}
          {stage==="matching" && counts.unresolved!==undefined && <span> · 已匹配 {counts.linked} · 未确定 {counts.unresolved}</span>}
          <span className="block">上次成功：<LocalDateTime value={r.last_succeeded_at} unavailable="尚无成功记录" /></span>
          {r.error && <span className="block text-amber-800">{r.error}</span>}
        </div>;
      })}
      {refreshError && <p role="alert">{refreshError}</p>}
    </div>
  </div>;
}
