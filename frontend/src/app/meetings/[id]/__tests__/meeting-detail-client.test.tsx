import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import MeetingDetailClient from "../meeting-detail-client";
import type { MeetingOut } from "@/lib/types";

import { saveSpeakerMappings } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, saveSpeakerMappings: vi.fn().mockResolvedValue(undefined) };
});

afterEach(cleanup);

it("displays Calendar participants when extracted attendees are empty", () => {
  const meeting: MeetingOut = {
    id: "meeting-1",
    recorded_at: "2026-09-02T08:15:00Z",
    title: "test",
    state: "awaiting_review",
    summary: null,
    transcript: null,
    action_items: [],
    extracted_json: { attendees: [] },
    calendar_participants: [
      { name: "Sphesihle Mhlongo", email: "sphesihle@taxconsulting.co.za", is_organizer: false },
      { name: "Wei Jiuyang", email: "wei.jiuyang@taxconsulting.co.za", is_organizer: true },
    ],
    organizer_upn: "wei.jiuyang@taxconsulting.co.za",
    email_recipients: [],
    approved_recipients: [],
    is_organizer: true,
    can_edit: true,
    can_request_edit_access: false,
    edit_access_status: "organizer",
    edit_access_requests: [],
    speaker_candidates: [],
    speaker_mappings: {},
    speaker_sample_labels: [],
  };

  render(<MeetingDetailClient
    meeting={meeting}
    upn="wei.jiuyang@taxconsulting.co.za"
    accessToken="offline-test-token"
  />);

  expect(screen.getByText("Sphesihle Mhlongo, Wei Jiuyang")).toBeInTheDocument();
});

it("shows existing edit and final approval controls for an Admin projection", async () => {
  const meeting: MeetingOut = {
    id: "meeting-admin", recorded_at: null, title: "Private meeting", state: "awaiting_review",
    summary: "AI-generated notes", transcript: "[Speaker A] Existing transcript",
    action_items: [{ id: "action-1", task: "Follow up", owner: null, deadline_text: null,
      deadline_iso: null, confidence: "high", source_quote: null, approved: false }],
    extracted_json: { discussion_points: [{ topic: "Plan", summary: "Discussed", outcome: null }] },
    calendar_participants: [{ name: "Owner", email: "owner@taxconsulting.co.za", is_organizer: true }],
    organizer_upn: "owner@taxconsulting.co.za", email_recipients: ["owner@taxconsulting.co.za"],
    approved_recipients: [], is_organizer: false, can_edit: true, can_approve: true,
    can_request_edit_access: false, edit_access_status: "none", edit_access_requests: [],
    speaker_candidates: [{ upn: "owner@taxconsulting.co.za", email: "owner@taxconsulting.co.za", display_name: "Owner" }],
    speaker_mappings: {}, speaker_sample_labels: ["Speaker A"],
  };

  const view = render(<MeetingDetailClient meeting={meeting} upn="admin@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByText("Discussed")).toBeInTheDocument();
  expect(screen.getByText("Existing transcript", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
  expect(screen.getByLabelText("Name for Speaker A")).toBeEnabled();
  expect(screen.getByRole("option", { name: "Owner" })).toHaveValue("owner@taxconsulting.co.za");
  expect(screen.getByRole("button", { name: "Save speaker names" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Name for Speaker A"), { target: { value: "owner@taxconsulting.co.za" } });
  fireEvent.click(screen.getByRole("button", { name: "Save speaker names" }));
  await waitFor(() => expect(saveSpeakerMappings).toHaveBeenCalledWith(
    "meeting-admin", { "Speaker A": "owner@taxconsulting.co.za" }, "token",
  ));

  view.rerender(<MeetingDetailClient
    meeting={{ ...meeting, speaker_mappings: { "Speaker A": "owner@taxconsulting.co.za" } }}
    upn="admin@taxconsulting.co.za"
    accessToken="token"
  />);
  expect(screen.getByLabelText("Name for Speaker A")).toHaveValue("owner@taxconsulting.co.za");
});

it("supports legacy string speaker candidates without object rendering", () => {
  const meeting: MeetingOut = {
    id: "meeting-legacy", recorded_at: null, title: "Legacy", state: "awaiting_review",
    summary: null, transcript: "[Speaker A] Existing transcript", action_items: [], extracted_json: null,
    calendar_participants: [], organizer_upn: "owner@taxconsulting.co.za", email_recipients: [], approved_recipients: [],
    is_organizer: true, can_edit: true, can_request_edit_access: false, edit_access_status: "organizer",
    edit_access_requests: [], speaker_candidates: ["owner@taxconsulting.co.za"], speaker_mappings: {}, speaker_sample_labels: [],
  };

  render(<MeetingDetailClient meeting={meeting} upn="owner@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByRole("option", { name: "owner@taxconsulting.co.za" })).toHaveValue("owner@taxconsulting.co.za");
  expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
});
