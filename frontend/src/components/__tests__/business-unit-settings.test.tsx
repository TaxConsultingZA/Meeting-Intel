import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BusinessUnitSettings, { BUSINESS_UNIT_SNOOZE_MS } from "../business-unit-settings";
import { chooseBusinessUnit, getBusinessUnits, getMe } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getMe: vi.fn(), getBusinessUnits: vi.fn(), chooseBusinessUnit: vi.fn(),
}));

const account = { upn: "new@example.test", display_name: "New", business_unit_id: null, business_unit_name: null, business_unit_version: 0, is_admin: false, is_subscribed: false, subscribed_at: null, registered_at: "2026-11-01T00:00:00Z" };
const units = [{ id: 1, name: "Africorp", is_selectable: true }, { id: 2, name: "Crypto Tax consulting", is_selectable: true }, { id: 3, name: "A very long Business Unit name for accessibility", is_selectable: true }];

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.open = false; this.dispatchEvent(new Event("close")); } });
  vi.mocked(getMe).mockResolvedValue(account);
  vi.mocked(getBusinessUnits).mockResolvedValue(units);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

function dialogOpen() { return (document.querySelector("dialog[aria-labelledby='bu-title']") as HTMLDialogElement | null)?.open ?? false; }

it("keeps the result list collapsed until the user opens or searches it", async () => {
  const user = userEvent.setup();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  expect(input).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("listbox", { name: "Business Unit results" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Show Business Units" }));
  expect(screen.getByRole("listbox", { name: "Business Unit results" })).toBeVisible();
  expect(screen.getByRole("option", { name: "Africorp" })).toBeVisible();
});

it("filters one searchable control and chooses an option with the keyboard", async () => {
  const user = userEvent.setup();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  await user.type(input, "crypto");
  expect(screen.getByRole("option", { name: "Crypto Tax consulting" })).toBeVisible();
  expect(screen.queryByRole("option", { name: "Africorp" })).toBeNull();
  await user.keyboard("{ArrowDown}{Enter}");
  expect(input).toHaveValue("Crypto Tax consulting");
  expect(screen.getByRole("button", { name: "Save Business Unit" })).toBeEnabled();
});

it("announces an empty result and returns focus to the trigger after Later", async () => {
  const user = userEvent.setup();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.change(input, { target: { value: "nothing-here" } });
  expect(screen.getByText("No matching Business Units.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Later" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Personal settings" })).toHaveFocus());
});

it("mounts exactly one dialog instance", async () => {
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  expect(document.querySelectorAll("dialog[aria-labelledby='bu-title']")).toHaveLength(1);
});

it("does not automatically open the chooser for an assigned user and shows compact settings on demand", async () => {
  vi.mocked(getMe).mockResolvedValue({ ...account, business_unit_id: 2, business_unit_name: "AI Department" });
  render(<BusinessUnitSettings token="mock:assigned@example.test" />);
  await waitFor(() => expect(dialogOpen()).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "Personal settings" }));
  expect(await screen.findByRole("dialog", { name: "Business Unit settings" })).toHaveTextContent("AI Department");
  expect(dialogOpen()).toBe(false);
});

it("uses the same per-user five-minute snooze for Later and close", async () => {
  const now = Date.parse("2026-11-12T10:00:00Z");
  vi.spyOn(Date, "now").mockReturnValue(now);
  const first = render(<BusinessUnitSettings token="mock:new@example.test" />);
  await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.click(screen.getByRole("button", { name: "Later" }));
  const expected = String(Date.now() + BUSINESS_UNIT_SNOOZE_MS);
  expect(localStorage.getItem("meeting-intel:business-unit-snooze:new@example.test")).toBe(expected);
  first.unmount();
  localStorage.clear();
  const second = render(<BusinessUnitSettings token="mock:new@example.test" />);
  await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.click(screen.getByRole("button", { name: "Close Business Unit dialog" }));
  expect(localStorage.getItem("meeting-intel:business-unit-snooze:new@example.test")).toBe(expected);
  second.unmount();
});

it("does not reopen during a snooze, but opens again after five minutes", async () => {
  let now = Date.parse("2026-11-12T10:00:00Z");
  vi.spyOn(Date, "now").mockImplementation(() => now);
  const first = render(<BusinessUnitSettings token="mock:new@example.test" />);
  await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.click(screen.getByRole("button", { name: "Later" }));
  first.unmount();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  await waitFor(() => expect(dialogOpen()).toBe(false));
  cleanup();
  now += BUSINESS_UNIT_SNOOZE_MS + 1;
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  await waitFor(() => expect(dialogOpen()).toBe(true));
});

it("reopens on the same page when the five-minute snooze expires", async () => {
  vi.useFakeTimers();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  await act(async () => { await Promise.resolve(); });
  expect(dialogOpen()).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Later" }));
  expect(dialogOpen()).toBe(false);
  await act(async () => { await vi.advanceTimersByTimeAsync(BUSINESS_UNIT_SNOOZE_MS); });
  expect(dialogOpen()).toBe(true);
  vi.useRealTimers();
});

it("shows a clear save failure without closing the dialog", async () => {
  vi.mocked(chooseBusinessUnit).mockRejectedValue(new Error("The Business Unit changed. Refresh and try again."));
  const user = userEvent.setup();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  await user.type(input, "afri{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Save Business Unit" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The Business Unit changed. Refresh and try again.");
});

it("saves a selected first Business Unit and closes the dialog", async () => {
  vi.mocked(chooseBusinessUnit).mockResolvedValue({ ...account, business_unit_id: 1, business_unit_name: "Africorp", business_unit_version: 1 });
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.change(input, { target: { value: "afri" } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Save Business Unit" }));
  await waitFor(() => expect(chooseBusinessUnit).toHaveBeenCalledWith("mock:new@example.test", { business_unit_id: 1, business_unit_version: 0 }));
  expect(screen.getByRole("status")).toHaveTextContent("Business Unit saved: Africorp.");
});

it("cancels a user's snooze after a successful save", async () => {
  localStorage.setItem("meeting-intel:business-unit-snooze:new@example.test", String(Date.now() + BUSINESS_UNIT_SNOOZE_MS));
  const saved = { ...account, business_unit_id: 1, business_unit_name: "Africorp", business_unit_version: 1 };
  vi.mocked(getMe).mockResolvedValueOnce(account).mockResolvedValueOnce(account).mockResolvedValue(saved);
  vi.mocked(chooseBusinessUnit).mockResolvedValue(saved);
  const first = render(<BusinessUnitSettings token="mock:new@example.test" />);
  await waitFor(() => expect(dialogOpen()).toBe(false));
  fireEvent.click(screen.getByRole("button", { name: "Personal settings" }));
  const input = await screen.findByRole("combobox", { name: "Search and choose a Business Unit" });
  fireEvent.change(input, { target: { value: "afri" } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.click(screen.getByRole("button", { name: "Save Business Unit" }));
  await waitFor(() => expect(localStorage.getItem("meeting-intel:business-unit-snooze:new@example.test")).toBeNull());
  first.unmount();
  render(<BusinessUnitSettings token="mock:new@example.test" />);
  await waitFor(() => expect(dialogOpen()).toBe(false));
});
