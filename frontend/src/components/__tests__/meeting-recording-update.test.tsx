import {afterEach,expect,it,vi} from "vitest";
import {act,cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import Update from "../meeting-recording-update";
import {getRecordingUpdateStatus,runRecordingUpdateStage,type RecordingUpdateStage,type RecordingUpdateResult} from "@/lib/api";
vi.mock("@/lib/api",()=>({getRecordingUpdateStatus:vi.fn(),runRecordingUpdateStage:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();vi.useRealTimers();});
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
  fireEvent.click(screen.getByRole("button",{name:"Update meetings and recordings"}));
  fireEvent.click(screen.getByRole("button",{name:"Updating…"}));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  expect(order).toEqual(["calendar","discovery","matching","refresh"]);
  expect(screen.getByText(/1 matched · 5 unmatched/)).toBeVisible();
  expect(screen.getAllByText("01 Sept 2026, 10:00 SAST").length).toBe(3);
});
it("shows each partial failure and retains last success while continuing safe steps",async()=>{
  vi.mocked(getRecordingUpdateStatus).mockResolvedValue([result("calendar")]);
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(token,stage)=>{
    if(stage==="calendar")throw new Error("secret vendor body");
    return {...result(stage),status:stage==="discovery"?"partial":"success",error:stage==="discovery"?"More pages pending":null};
  });
  const refresh=vi.fn().mockResolvedValue(undefined);
  render(<Update token="owner-token" onUpdated={refresh}/>);
  await waitFor(()=>expect(getRecordingUpdateStatus).toHaveBeenCalledOnce());
  await act(async()=>{});
  fireEvent.click(screen.getByRole("button",{name:"Update meetings and recordings"}));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  expect(screen.getByText("Calendar sync: Failed")).toBeVisible();
  expect(screen.getByText("Recording discovery: Partially complete")).toBeVisible();
  expect(screen.queryByText(/secret vendor body/)).not.toBeInTheDocument();
});

it("does not replace fresh results with a slow initial status response",async()=>{
  let initial!:(rows:RecordingUpdateResult[])=>void;
  vi.mocked(getRecordingUpdateStatus).mockReturnValue(new Promise(resolve=>{initial=resolve;}));
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(token,stage)=>result(stage));
  const refresh=vi.fn().mockResolvedValue(undefined);
  render(<Update token="owner-token" onUpdated={refresh}/>);
  fireEvent.click(screen.getByRole("button",{name:"Update meetings and recordings"}));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  await act(async()=>initial([]));
  expect(screen.getByText(/1 matched · 5 unmatched/)).toBeVisible();
});

it.each(["success","failed"] as const)("hides completed %s results after a minute and reopens them without another update",async(status)=>{
  vi.mocked(getRecordingUpdateStatus).mockResolvedValue([{...result("calendar"),status,error:status==="failed"?"Calendar access was denied. Try the update again.":null}]);
  render(<Update token="owner-token" onUpdated={vi.fn()}/>);
  const history=await screen.findByRole("button",{name:/Update results/});
  expect(screen.queryByRole("region")).not.toBeInTheDocument();
  vi.useFakeTimers();
  fireEvent.click(history);
  expect(screen.getByRole("region")).toBeVisible();
  await act(async()=>{await vi.advanceTimersByTimeAsync(59_999);});
  expect(screen.getByRole("region")).toBeVisible();
  await act(async()=>{await vi.advanceTimersByTimeAsync(1);});
  expect(screen.queryByRole("region")).not.toBeInTheDocument();
  fireEvent.click(history);
  expect(screen.getByRole("region")).toBeVisible();
  if(status==="failed")expect(screen.getByText("Calendar access was denied. Try the update again.")).toBeVisible();
  expect(runRecordingUpdateStage).not.toHaveBeenCalled();
  expect(getRecordingUpdateStatus).toHaveBeenCalledOnce();
});

it("keeps running progress visible beyond a minute and starts dismissal after completion",async()=>{
  let finish!:(value:RecordingUpdateResult)=>void;
  vi.mocked(getRecordingUpdateStatus).mockResolvedValue([]);
  vi.mocked(runRecordingUpdateStage).mockImplementation(async(_token,stage)=>stage==="calendar"?new Promise(resolve=>{finish=resolve;}):result(stage));
  render(<Update token="owner-token" onUpdated={vi.fn().mockResolvedValue(undefined)}/>);
  await act(async()=>{});
  vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button",{name:"Update meetings and recordings"}));
  await act(async()=>{await vi.advanceTimersByTimeAsync(120_000);});
  expect(screen.getByText("Calendar sync in progress…")).toBeVisible();
  expect(screen.getByRole("button",{name:"Updating…"})).toBeDisabled();
  await act(async()=>{finish(result("calendar"));});
  expect(screen.getByText("Update complete.")).toBeVisible();
  await act(async()=>{await vi.advanceTimersByTimeAsync(60_000);});
  expect(screen.queryByRole("region")).not.toBeInTheDocument();
});

it("retries loading saved results without running Graph update stages",async()=>{
  vi.mocked(getRecordingUpdateStatus).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce([result("calendar")]);
  render(<Update token="owner-token" onUpdated={vi.fn()}/>);
  fireEvent.click(await screen.findByRole("button",{name:/Update results/}));
  expect(await screen.findByText("Calendar sync: Complete")).toBeVisible();
  expect(getRecordingUpdateStatus).toHaveBeenCalledTimes(2);
  expect(runRecordingUpdateStage).not.toHaveBeenCalled();
});

it("formats saved notification time without running discovery or matching",async()=>{
 vi.mocked(getRecordingUpdateStatus).mockResolvedValue([
 {...result("calendar"),last_succeeded_at:"2026-10-22T14:50:32+08:00"},
 {...result("discovery"),last_succeeded_at:null},
 ]);
 render(<Update token="token" onUpdated={vi.fn()}/>);
 fireEvent.click(await screen.findByRole("button",{name:"Update results"}));
 expect(screen.getByText("22 Oct 2026, 08:50 SAST")).toBeVisible(); expect(screen.getByText("No successful update yet")).toBeVisible();
 expect(runRecordingUpdateStage).not.toHaveBeenCalled();
});
