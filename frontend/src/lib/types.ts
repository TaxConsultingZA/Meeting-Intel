/**
 * All states a meeting recording can pass through.
 * Happy path: queued → downloading → transcribing → extracting → awaiting_review → approved → sent
 */
export type ProcessingState =
  | "queued"
  | "downloading"
  | "transcribing"
  | "extracting"
  | "awaiting_review"
  | "approved"
  | "sent"
  | "failed"
  | "cancelled"
  | "cancel_requested"
  | "processing"
  | "completed";

export type RecordingProcessingStatus =
  | "queued"
  | "processing"
  | "downloading"
  | "transcribing"
  | "extracting"
  | "cancel_requested"
  | "completed"
  | "failed"
  | "cancelled";

export type MeetingReviewStatus = "awaiting_review" | "approved" | "sent";

/** Confidence level the AI extractor assigns to each identified action item. */
export type Confidence = "high" | "medium" | "low";

/** A single action item as returned by GET /reviews/{id}. */
export interface ActionItemOut {
  id: string;
  task: string;
  owner: string | null;
  deadline_text: string | null;
  deadline_iso: string | null;
  confidence: Confidence;
  source_quote: string | null;
  approved: boolean;
}

/** Partial update payload sent to PATCH /reviews/action-items/{id}. All fields optional. */
export interface ActionItemEdit {
  task?: string;
  owner?: string;
  deadline_iso?: string;
  confidence?: Confidence;
}

/** Full meeting representation returned by the reviews API. */
export interface CalendarParticipant {
  name: string;
  email: string;
  is_organizer: boolean;
}

export interface MeetingOut {
  id: string;
  recorded_at?: string | null;
  title: string | null;
  state: ProcessingState;
  summary: string | null;
  transcript?: string | null;
  action_items: ActionItemOut[];
  // rich fields from extracted_json (may be absent on older records)
  extracted_json?: ExtractedJson | null;
  calendar_participants: CalendarParticipant[];
  organizer_upn?: string | null;
  error?: string | null;
  email_recipients: string[];
  approved_recipients: string[];
  is_organizer: boolean;
  can_edit: boolean;
  can_request_edit_access: boolean;
  edit_access_status: "none" | "pending" | "approved" | "denied" | "organizer";
  edit_access_requests: { requester_upn: string; status: string; requested_at: string | null }[];
  speaker_candidates: string[];
  speaker_mappings: Record<string, string | null>;
  speaker_sample_labels: string[];
}

export interface ExtractedJson {
  extraction_mode?: "structured" | "transcript_only";
  objective?: string;
  meeting_time?: string | null;
  attendees?: string[];
  apologies?: string[];
  platform?: string;
  speaker_highlights?: SpeakerHighlight[];
  discussion_points?: DiscussionPoint[];
  action_items?: ExtractedActionItem[];
  deliverables?: Deliverable[];
  risks?: Risk[];
  next_steps?: string[];
  next_meeting?: NextMeeting | null;
  summary?: string;
  speaker_mappings?: Record<string, string | null>;
  transcript_segments?: Array<{
    speaker: string;
    text: string;
    start: number;
    end: number;
  }>;
}

export interface SpeakerHighlight {
  speaker: string;
  role: string | null;
  key_points: string[];
}

export interface DiscussionPoint {
  topic: string;
  summary: string;
  outcome: string | null;
}

export interface ExtractedActionItem {
  action: string;
  assigned_to: string | null;
  department: string | null;
  reason: string | null;
  expected_outcome: string | null;
  due_date: string | null;
  confidence: Confidence;
  source_quote: string | null;
}

export interface Deliverable {
  deliverable: string;
  responsible: string | null;
  delivery_method: string | null;
  due_date: string | null;
  expected_outcome: string | null;
}

export interface Risk {
  item: string;
  impact: string | null;
  resolution: string | null;
  owner: string | null;
}

export interface NextMeeting {
  proposed_date: string | null;
  proposed_time: string | null;
  agenda_focus: string | null;
}

/** A Teams calendar event returned by GET /calendar/upcoming. */
export interface CalendarEvent {
  event_id: string;
  subject: string;
  start: string | null;
  start_tz: string;
  end: string | null;
  organizer_name: string | null;
  organizer_email: string | null;
  attendees: string[];
  attendee_count: number;
  platform: string;
  location: string | null;
  status: "upcoming" | "in_progress";
}

/** A single in-app notification item returned by GET /notifications. */
export interface AppNotification {
  id: string;
  type: "ready_for_review" | "notes_sent" | "failed" | "processing";
  title: string;
  message: string;
  time: string;
  link: string | null;
}

/** A business unit within Taxconsulting SA. */
export interface BusinessUnit {
  id: number;
  name: string;
}

/** A user registered on the Meeting Intelligence platform. */
export interface RegisteredUser {
  upn: string;
  display_name: string | null;
  business_unit_id: number | null;
  business_unit_name: string | null;
  is_admin: boolean;
  is_subscribed: boolean;
  subscribed_at: string | null;
  registered_at: string;
}

export interface SyncState {
  source: "calendar" | "onedrive" | string;
  status: "never" | "success" | "failed" | string;
  last_attempted_at: string | null;
  last_succeeded_at: string | null;
  last_error: string | null;
}

/** A recording file visible in the user's OneDrive, with its current processing state if imported. */
export interface AvailableRecording {
  job?: RecordingJobOut;
  drive_item_id: string;
  drive_id: string;
  name: string;
  size: number | null;
  created_at: string | null;
  already_imported: boolean;
  meeting_id: string | null;
  meeting_state: ProcessingState | null;
  meeting_error: string | null;
}

export interface RecordingJobOut {
  job_id: string;
  drive_item_id: string;
  meeting_id: string | null;
  title: string | null;
  status: string;
  processing_status: RecordingProcessingStatus;
  review_status: MeetingReviewStatus | null;
  /** @deprecated Compatibility alias for processing_status. */
  phase: RecordingProcessingStatus;
  attempts: number;
  max_attempts: number;
  error: string | null;
  can_retry: boolean;
  can_cancel: boolean;
  can_reprocess: boolean;
  processing_enabled: boolean;
}
