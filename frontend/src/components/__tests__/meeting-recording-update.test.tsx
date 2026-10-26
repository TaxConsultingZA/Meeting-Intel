import {afterEach,expect,it,vi} from "vitest";
import {act,cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import Update from "../meeting-recording-update";
import {getRecordingUpdateStatus,runRecordingUpdateStage,type RecordingUpdateStage,type RecordingUpdateResult} from "@/lib/api";
vi.mock("@/lib/api",()=>({getRecordingUpdateStatus:vi.fn(),runRecordingUpdateStage:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
function result(stage:RecordingUpdateStage):RecordingUpdateResult {
  return {stage,status:"success",counts:{events:3,new:1,changed:2,linked:1,unresolved:5},
    error:null,last_attempted_at:"2026-09-01T08:00:00Z",last_succeeded_at:"2026-09-01T08:00:00Z"};
}
it("runs calendar then incremental discovery then matching and refreshes once",async()=>{
  vi.mocked(getRecordingUpdateStatus).mockResolvedValue([]);
  const order:string[]=[];
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(token,stage)=>{order.push(stage);return result(stage);});
  const refresh=vi.fn(async()=>{order.push("refresh");});
  render(<Update token="owner-token" onUpdated={refresh}/>);
  fireEvent.click(screen.getByRole("button",{name:"更新会议和录音"}));
  fireEvent.click(screen.getByRole("button"));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  expect(order).toEqual(["calendar","discovery","matching","refresh"]);
  expect(screen.getByText(/已匹配 1 · 未确定 5/)).toBeVisible();
  expect(screen.getAllByText("01 Sept 2026, 10:00").length).toBe(3);
});
it("shows each partial failure and retains last success while continuing safe steps",async()=>{
  vi.mocked(getRecordingUpdateStatus).mockResolvedValue([result("calendar")]);
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(token,stage)=>{
    if(stage==="calendar")throw new Error("secret vendor body");
    return {...result(stage),status:stage==="discovery"?"partial":"success",error:stage==="discovery"?"More pages pending":null};
  });
  const refresh=vi.fn().mockResolvedValue(undefined);
  render(<Update token="owner-token" onUpdated={refresh}/>);
  await screen.findByText("01 Sept 2026, 10:00");
  fireEvent.click(screen.getByRole("button",{name:"更新会议和录音"}));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  expect(screen.getByText("日历同步：失败")).toBeVisible();
  expect(screen.getByText("增量发现录音：部分完成")).toBeVisible();
  expect(screen.queryByText(/secret vendor body/)).not.toBeInTheDocument();
});

it("does not replace fresh results with a slow initial status response",async()=>{
  let initial!:(rows:RecordingUpdateResult[])=>void;
  vi.mocked(getRecordingUpdateStatus).mockReturnValue(new Promise(resolve=>{initial=resolve;}));
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(token,stage)=>result(stage));
  const refresh=vi.fn().mockResolvedValue(undefined);
  render(<Update token="owner-token" onUpdated={refresh}/>);
  fireEvent.click(screen.getByRole("button",{name:"更新会议和录音"}));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  await act(async()=>initial([]));
  expect(screen.getByText(/已匹配 1 · 未确定 5/)).toBeVisible();
});
