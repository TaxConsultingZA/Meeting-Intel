import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import MeetingDetailClient from "../meeting-detail-client";
import type { MeetingOut } from "@/lib/types";

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

it("shows existing edit and final approval controls for an Admin projection", () => {
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
    speaker_candidates: ["owner@taxconsulting.co.za"], speaker_mappings: {}, speaker_sample_labels: ["Speaker A"],
  };

  render(<MeetingDetailClient meeting={meeting} upn="admin@taxconsulting.co.za" accessToken="token" />);

  expect(screen.getByText("Discussed")).toBeInTheDocument();
  expect(screen.getByText("Existing transcript", { exact: false })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Approve Meeting Notes/ })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(2);
  expect(screen.getByLabelText("Name for Speaker A")).toBeEnabled();
  expect(screen.getByRole("button", { name: "Save speaker names" })).toBeInTheDocument();
});
