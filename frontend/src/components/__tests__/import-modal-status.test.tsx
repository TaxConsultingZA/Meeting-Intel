import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ImportModal from "../import-modal";
import { discoverOwnRecordings, runRecordingUpdateStage, getAvailableRecordings, getRecordingJobs, importRecording, reprocessRecording } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getAvailableRecordings: vi.fn(),
  getRecordingJobs: vi.fn(),
  importRecording: vi.fn(),
  reprocessRecording: vi.fn(),
  cancelRecordingJob: vi.fn(),
  retryRecordingJob: vi.fn(),
  discoverOwnRecordings: vi.fn(),
  runRecordingUpdateStage: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

const cachedRecording = {
  drive_item_id: "cached-item", drive_id: "drive-1", name: "cached.mp4", size: 1024,
  created_at: "2026-09-02T08:15:00Z", already_imported: false,
  meeting_id: null, meeting_state: null, meeting_error: null,
};

it("keeps date and size in separate columns and exposes an easy fixed close control",()=>{
  render(<ImportModal upn="offline" onClose={vi.fn()} initialRecordings={[{
    ...cachedRecording,created_at:"2026-09-01 08:41:58+00:00",size:544023
  }]}/>);
  const date=screen.getByText("01 Sept 2026, 10:41 SAST").closest("td");
  const size=screen.getByText("531 KB").closest("td");
  expect(date).not.toBe(size);
  expect(screen.queryByText(/The transcript and AI notes will appear/)).not.toBeInTheDocument();
  expect(screen.getByRole("button",{name:"Close recording dialog"})).toHaveClass("h-11","w-11");
  expect(screen.queryByRole("button", {name: /^Close$/})).not.toBeInTheDocument();
});

it("shows the actual file identity without per-row association actions", () => {
  const filename = "Test-20260901_164158-会议记录.mp4";
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()}
    initialRecordings={[{ ...cachedRecording, name: "Unrelated calendar title", original_filename: filename,
      already_imported: true, meeting_id: "existing-review", meeting_state: "awaiting_review", calendar_matched: true }]} />);

  expect(screen.getByText(filename)).toHaveAttribute("title", filename);
  expect(screen.queryByRole("button",{name:"Manage calendar link"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Discover files"})).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View" })).toHaveAttribute("href", "/meetings/existing-review");
  expect(importRecording).not.toHaveBeenCalled();
  expect(reprocessRecording).not.toHaveBeenCalled();
});

it("labels a recording without a calendar link and keeps Transcribe available", () => {
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()}
    initialRecordings={[{ ...cachedRecording, calendar_matched: false }]} />);
  expect(screen.getByText("No calendar meeting linked")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Transcribe" })).toBeEnabled();
  expect(importRecording).not.toHaveBeenCalled();
});

it.each(["pending", "completed"] as const)("keeps %s recording actions separate from calendar matching", (status) => {
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()}
    initialRecordings={[{ ...cachedRecording, calendar_matched: false, already_imported: true,
      meeting_id: "recording-review", job: {
        job_id: "job", drive_item_id: cachedRecording.drive_item_id,
        meeting_id: "recording-review", title: "cached.mp4", status,
        processing_status: status === "pending" ? "queued" : "completed",
        review_status: null, phase: status === "pending" ? "queued" : "completed", attempts: 1, max_attempts: 3,
        error: null, can_retry: false, can_cancel: status === "pending",
        can_reprocess: false, processing_enabled: false,
      } }]} />);
  expect(screen.getByText("No calendar meeting linked")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View" })).toHaveAttribute("href", "/meetings/recording-review");
  expect(screen.queryByRole("button", { name: "Transcribe" })).not.toBeInTheDocument();
  expect(Boolean(screen.queryByRole("button", { name: "Cancel" }))).toBe(status === "pending");
  expect(importRecording).not.toHaveBeenCalled();
});

it("describes an empty saved list without claiming Refresh scans OneDrive", () => {
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} initialRecordings={[]} />);
  expect(screen.getByText(/Use Update meetings and recordings/)).toBeInTheDocument();
  expect(screen.queryByText(/No MP4 recordings were found in your OneDrive/)).not.toBeInTheDocument();
});

it("opens immediately with a skeleton while recordings load asynchronously", async () => {
  let resolveRecordings!: (recordings: typeof cachedRecording[]) => void;
  vi.mocked(getAvailableRecordings).mockReturnValue(new Promise((resolve) => {
    resolveRecordings = resolve;
  }));
  vi.mocked(getRecordingJobs).mockResolvedValue([]);

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} />);

  expect(screen.getByRole("dialog", { name: "Process a Past Recording" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Loading recordings" })).toBeInTheDocument();
  await waitFor(() => expect(getAvailableRecordings).toHaveBeenCalledOnce());

  resolveRecordings([cachedRecording]);
  expect(await screen.findByText("cached.mp4")).toBeInTheDocument();
  expect(screen.queryByRole("status", { name: "Loading recordings" })).not.toBeInTheDocument();
});

it("shows completed processing separately from awaiting review", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([{
    drive_item_id: "item-1",
    drive_id: "drive-1",
    name: "test.mp4",
    size: 1024,
    created_at: "2026-09-02T08:15:00Z",
    already_imported: true,
    meeting_id: "meeting-1",
    meeting_state: "awaiting_review",
    meeting_error: null,
  }]);
  vi.mocked(getRecordingJobs).mockResolvedValue([{
    job_id: "job-1",
    drive_item_id: "item-1",
    meeting_id: "meeting-1",
    title: "test",
    status: "completed",
    processing_status: "completed",
    review_status: "awaiting_review",
    phase: "completed",
    attempts: 1,
    max_attempts: 3,
    error: null,
    can_retry: false,
    can_cancel: false,
    can_reprocess: true,
    processing_enabled: false,
  }]);

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} />);

  await waitFor(() => expect(screen.getByText("Completed")).toBeInTheDocument());
  expect(screen.getByRole("columnheader", { name: "Processing" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Review" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  expect(screen.getByText("Awaiting Review")).toBeInTheDocument();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: "Reprocess" }));
  await waitFor(() => expect(reprocessRecording).toHaveBeenCalledWith("item-1", "drive-1", "owner@taxconsulting.co.za"));
  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
});

it("shows approved completed recordings as view-only", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([{
    drive_item_id: "item-2", drive_id: "drive-1", name: "approved.mp4", size: 2048,
    created_at: "2026-09-02T08:15:00Z", already_imported: true,
    meeting_id: "meeting-2", meeting_state: "approved", meeting_error: null,
  }]);
  vi.mocked(getRecordingJobs).mockResolvedValue([{
    job_id: "job-2", drive_item_id: "item-2", meeting_id: "meeting-2", title: "approved",
    status: "completed", processing_status: "completed", review_status: "approved",
    phase: "completed", attempts: 1, max_attempts: 3, error: null,
    can_retry: false, can_cancel: false, can_reprocess: false, processing_enabled: false,
  }]);

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} />);

  await waitFor(() => expect(screen.getByText("Approved")).toBeInTheDocument());
  expect(screen.getByText("Completed")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "View" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reprocess" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
});

it("renders prefetched recordings immediately then revalidates both saved reads", async () => {
  vi.mocked(getAvailableRecordings).mockResolvedValue([cachedRecording]);
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  const onRecordingsLoaded = vi.fn();
  const first = render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} onRecordingsLoaded={onRecordingsLoaded} />);

  expect(await screen.findByText("cached.mp4")).toBeInTheDocument();
  await waitFor(() => expect(onRecordingsLoaded).toHaveBeenCalled());
  const cached = onRecordingsLoaded.mock.calls.at(-1)?.[0];
  expect(getAvailableRecordings).toHaveBeenCalledOnce();
  first.unmount();

  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} initialRecordings={cached} onRecordingsLoaded={vi.fn()} />);
  expect(screen.getByText("cached.mp4")).toBeInTheDocument();
  await waitFor(() => expect(getAvailableRecordings).toHaveBeenCalledTimes(2));
  expect(screen.getByText("Recording list and task status loaded successfully.")).toBeVisible();
});

it("keeps cached recordings visible when an explicit refresh fails", async () => {
  vi.mocked(getAvailableRecordings).mockRejectedValue(new Error("OneDrive unavailable"));
  vi.mocked(getRecordingJobs).mockResolvedValue([]);
  render(<ImportModal upn="owner@taxconsulting.co.za" onClose={vi.fn()} initialRecordings={[cachedRecording]} />);

  expect(screen.getByText("cached.mp4")).toBeInTheDocument();
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Showing the previously loaded recordings");
  expect(screen.getByText("cached.mp4")).toBeInTheDocument();
  await waitFor(() => expect(getAvailableRecordings).toHaveBeenCalledTimes(2));
});

it("uses SAST and keeps absent recording dates unavailable",()=>{
 render(<ImportModal upn="offline" onClose={vi.fn()} initialRecordings={[
 {...cachedRecording,created_at:"2026-10-22T14:50:32+08:00"},
 {...cachedRecording,drive_item_id:"unknown",name:"unknown.mp4",created_at:null},
 ]}/>);
 expect(screen.getByText("Recordings · SAST")).toBeVisible(); expect(screen.getByText("22 Oct 2026, 08:50 SAST")).toBeVisible();
 expect(screen.getByText("Recording date unavailable")).toBeVisible(); expect(screen.queryByText(/Africa\/Johannesburg/)).not.toBeInTheDocument();
});

it("orders actual instants descending with unknown dates last and separates Teams verification",()=>{
 render(<ImportModal upn="offline" onClose={vi.fn()} initialRecordings={[
 {...cachedRecording,drive_item_id:"unknown",name:"unknown.mp4",created_at:null},
 {...cachedRecording,drive_item_id:"old",name:"old.mp4",created_at:"2026-09-01T08:41:58Z"},
 {...cachedRecording,drive_item_id:"new",name:"new.mp4",created_at:"2026-10-22T14:50:32+08:00",teams_meeting_verified:true,teams_meeting_title:"Verified Teams",calendar_matched:false,identity_reason:"No verified Outlook event ID."},
 ]}/>);
 const rows=screen.getAllByRole("row");
 expect(rows[1]).toHaveTextContent("new.mp4"); expect(rows[2]).toHaveTextContent("old.mp4"); expect(rows[3]).toHaveTextContent("unknown.mp4");
 expect(rows[1]).toHaveTextContent("Teams meeting verified: Verified Teams");
 expect(rows[1]).toHaveTextContent("No calendar meeting linked");
});

it("keeps the actual legacy filename and same unverified notice as the meeting views",()=>{
 render(<ImportModal upn="offline" onClose={vi.fn()} initialRecordings={[{...cachedRecording,name:"Trust wrong title",original_filename:"Test-original.mp4",association_status:"needs_review",calendar_matched:false,calendar_title:"Trust wrong title",identity_reason:"Previous calendar association is unverified; saved results are preserved."}]}/>);
 expect(screen.getByText("Test-original.mp4")).toBeVisible();
 expect(screen.getByText("Calendar association unverified. Existing results are preserved.")).toBeVisible();
 expect(screen.queryByText(/Trust wrong title/)).not.toBeInTheDocument();
 expect(screen.getByText("No calendar meeting linked")).toBeVisible();
});

it("styles Transcribe as a deep blue primary action and Refresh only reloads saved lists",async()=>{
 vi.mocked(getAvailableRecordings).mockResolvedValue([cachedRecording]);
 vi.mocked(getRecordingJobs).mockResolvedValue([]);
 render(<ImportModal upn="owner-token" onClose={vi.fn()} initialRecordings={[cachedRecording]}/>);
 const transcribe=screen.getByRole("button",{name:"Transcribe"});
 expect(transcribe).toHaveClass("bg-[#003366]","text-white");
 expect(transcribe).not.toHaveClass("bg-white");
 const refresh=screen.getByRole("button",{name:"Refresh"});
 expect(refresh).toHaveAttribute("title","Reload recording list");
 await screen.findByText("Recording list and task status loaded successfully.");
 fireEvent.click(refresh);
 await waitFor(()=>expect(getAvailableRecordings).toHaveBeenCalledTimes(2));
 expect(getRecordingJobs).toHaveBeenCalledTimes(2);
 expect(discoverOwnRecordings).not.toHaveBeenCalled();
 expect(runRecordingUpdateStage).not.toHaveBeenCalled();
 expect(importRecording).not.toHaveBeenCalled();
 expect(reprocessRecording).not.toHaveBeenCalled();
});

const statusPollJob = {
 job_id:"poll-job",drive_item_id:cachedRecording.drive_item_id,meeting_id:null,title:"Saved recording",
 status:"pending" as const,processing_status:"queued" as const,review_status:null,phase:"queued" as const,attempts:0,max_attempts:3,error:null,
 can_retry:false,can_cancel:false,can_reprocess:false,processing_enabled:false,
};

it("clears a failed background read only after both list and task status recover",async()=>{
 vi.useFakeTimers();
 Object.defineProperty(document,"visibilityState",{configurable:true,value:"visible"});
 vi.mocked(getAvailableRecordings).mockResolvedValue([cachedRecording]);
 vi.mocked(getRecordingJobs).mockResolvedValueOnce([statusPollJob]).mockRejectedValueOnce(new Error("Offline")).mockResolvedValue([statusPollJob]);
 render(<ImportModal upn="token" onClose={vi.fn()}/>);
 await act(()=>vi.advanceTimersByTimeAsync(0));
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 expect(screen.getByRole("alert")).toBeVisible();
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 expect(getAvailableRecordings).toHaveBeenCalledTimes(2);
 expect(screen.getByText("Recording list and task status loaded successfully.")).toBeVisible();
 expect(importRecording).not.toHaveBeenCalled();
 expect(runRecordingUpdateStage).not.toHaveBeenCalled();
});

it("does not certify a cached list when only the list request succeeds",async()=>{
 vi.mocked(getAvailableRecordings).mockResolvedValue([{...cachedRecording,name:"Unverified newer file.mp4"}]);
 vi.mocked(getRecordingJobs).mockRejectedValue(new Error("Status unavailable"));
 render(<ImportModal upn="token" onClose={vi.fn()} initialRecordings={[cachedRecording]}/>);
 expect(screen.getByText(/Showing cached recordings/)).toBeVisible();
 expect(await screen.findByRole("alert")).toBeVisible();
 expect(screen.queryByText("Recording list and task status loaded successfully.")).not.toBeInTheDocument();
 expect(screen.getByText("cached.mp4")).toBeVisible();
 expect(screen.queryByText("Unverified newer file.mp4")).not.toBeInTheDocument();
});

it("stops background retries after HTTP 401 and asks for a normal login",async()=>{
 vi.useFakeTimers();
 Object.defineProperty(document,"visibilityState",{configurable:true,value:"visible"});
 vi.mocked(getAvailableRecordings).mockResolvedValue([cachedRecording]);
 vi.mocked(getRecordingJobs).mockResolvedValueOnce([statusPollJob]).mockRejectedValue(Object.assign(new Error("Not signed in"),{status:401}));
 render(<ImportModal upn="token" onClose={vi.fn()}/>);
 await act(()=>vi.advanceTimersByTimeAsync(0));
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 expect(screen.getByRole("alert")).toHaveTextContent("Your session could not be verified");
 expect(screen.getByRole("link",{name:"Sign in again"})).toHaveAttribute("href","/login");
 await act(()=>vi.advanceTimersByTimeAsync(20000));
 expect(getRecordingJobs).toHaveBeenCalledTimes(2);
 expect(screen.queryByText("Recording list and task status loaded successfully.")).not.toBeInTheDocument();
});

it("retains the cached warning if recovery succeeds only for task status",async()=>{
 vi.useFakeTimers();
 Object.defineProperty(document,"visibilityState",{configurable:true,value:"visible"});
 vi.mocked(getAvailableRecordings).mockResolvedValueOnce([cachedRecording]).mockRejectedValueOnce(new Error("List read failed")).mockResolvedValue([cachedRecording]);
 vi.mocked(getRecordingJobs).mockResolvedValueOnce([statusPollJob]).mockRejectedValueOnce(new Error("Temporary status failure")).mockResolvedValue([statusPollJob]);
 render(<ImportModal upn="token" onClose={vi.fn()}/>);
 await act(()=>vi.advanceTimersByTimeAsync(0));
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 expect(screen.getByRole("alert")).toBeVisible();
 expect(screen.queryByText("Recording list and task status loaded successfully.")).not.toBeInTheDocument();
 await act(()=>vi.advanceTimersByTimeAsync(5000));
 expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 expect(screen.getByText("Recording list and task status loaded successfully.")).toBeVisible();
});
