import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RecordingAssociation from "../recording-association";
import { getRecordingCalendarChoices, setRecordingAssociation } from "@/lib/api";

vi.mock("@/lib/api", () => ({ getRecordingCalendarChoices:vi.fn(),setRecordingAssociation:vi.fn() }));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const recording={drive_item_id:"exact-item",drive_id:"owner-drive",name:"Test.mp4",size:1,
  created_at:null,already_imported:false,meeting_id:null,meeting_state:null,meeting_error:null};

it("keeps an unmatched recording independent using its exact identity",async()=>{
  vi.mocked(getRecordingCalendarChoices).mockResolvedValue([]);
  vi.mocked(setRecordingAssociation).mockResolvedValue({ok:true});
  const saved=vi.fn().mockResolvedValue(undefined);
  render(<RecordingAssociation recording={recording} token="signed-token" onSaved={saved}/>);
  fireEvent.click(screen.getByRole("button",{name:"Manage calendar link"}));
  await screen.findByText(/No calendar choices/);
  fireEvent.click(screen.getByRole("button",{name:"Keep independent"}));
  await waitFor(()=>expect(setRecordingAssociation).toHaveBeenCalledWith("signed-token","owner-drive","exact-item",null));
  expect(saved).toHaveBeenCalledOnce();
});

it("requires choosing a stable event ID before linking",async()=>{
  vi.mocked(getRecordingCalendarChoices).mockResolvedValue([{id:"stable-event",iCalUId:"ical",
    subject:"Test",start:{dateTime:"2026-09-01T08:30:00Z",timeZone:"UTC"},
    end:{dateTime:"2026-09-01T09:00:00Z",timeZone:"UTC"},isCancelled:true}]);
  vi.mocked(setRecordingAssociation).mockResolvedValue({ok:true});
  render(<RecordingAssociation recording={recording} token="signed-token" onSaved={vi.fn().mockResolvedValue(undefined)}/>);
  fireEvent.click(screen.getByRole("button",{name:"Manage calendar link"}));
  await screen.findByRole("option",{name:/Test.*Cancelled/});
  expect(screen.getByRole("button",{name:"Link selected event"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Calendar event"),{target:{value:"stable-event"}});
  fireEvent.click(screen.getByRole("button",{name:"Link selected event"}));
  await waitFor(()=>expect(setRecordingAssociation).toHaveBeenCalledWith("signed-token","owner-drive","exact-item","stable-event"));
});
