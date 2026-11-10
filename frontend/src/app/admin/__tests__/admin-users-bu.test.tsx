import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { getRegisteredUsers } from "@/lib/api";
import AdminClient from "../admin-client";
vi.mock("../admin-workbench",()=>({default:()=>null}));
vi.mock("@/lib/api",async()=>({...await vi.importActual<typeof import("@/lib/api")>("@/lib/api"),getBusinessUnits:vi.fn().mockResolvedValue([{id:3,name:"IT",is_selectable:true},{id:1,name:"Tax Technical",is_selectable:false}]),getRegisteredUsers:vi.fn().mockResolvedValue([{id:"1",upn:"assigned@example.test",display_name:"Assigned user",business_unit_id:1,business_unit_name:"Tax Technical",registered_at:"2026-11-05T08:00:00Z"},{id:"2",upn:"unassigned@example.test",display_name:"Unassigned user",business_unit_id:null,business_unit_name:null,registered_at:"2026-11-05T08:00:00Z"}])}));
afterEach(cleanup);
it("filters a historical BU and groups Unassigned separately",async()=>{
 render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="test"/>);
 await screen.findByText("Assigned user");
 fireEvent.change(screen.getByLabelText("Filter users by Business Unit"),{target:{value:"1"}});
 expect(screen.queryByText("Unassigned user")).toBeNull();
 expect(screen.getByText("Assigned user")).toBeVisible();
 fireEvent.click(screen.getByTitle("Edit"));
 expect(within(screen.getByLabelText("Correct Business Unit")).getByRole("option", {name: "Tax Technical (historical)"})).toBeDisabled();
 fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
 fireEvent.change(screen.getByLabelText("Filter users by Business Unit"),{target:{value:"unassigned"}});
 fireEvent.change(screen.getByLabelText("User display mode"),{target:{value:"grouped"}});
 expect(screen.getByRole("row",{name:/^Unassigned$/})).toBeVisible();
 expect(screen.queryByText("Assigned user")).toBeNull();
 expect(screen.getByText(/BU does not grant login or meeting access/)).toBeVisible();
});
it("refreshes the user list after a personal Business Unit selection", async () => {
  vi.mocked(getRegisteredUsers).mockClear();
  render(<AdminClient initialRequests={[]} callerUpn="admin@example.test" accessToken="test"/>);
  await screen.findByText("Assigned user");
  fireEvent(window, new Event("business-unit-updated"));
  await waitFor(() => expect(getRegisteredUsers).toHaveBeenCalledTimes(2));
});
