"use client";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { X, FolderOpen, Loader2, CheckCircle2, Download, RefreshCw, AlertCircle, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { getAvailableRecordings, importRecording, reprocessRecording } from "@/lib/api";
import type { AvailableRecording, ProcessingState } from "@/lib/types";

function formatBytes(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-ZA", {
    day: "2-digit", month: "short", year: "numeric",
  });
}

const STATE_LABEL: Record<ProcessingState, string> = {
  queued: "Queued",
  downloading: "Downloading",
  transcribing: "Transcribing",
  extracting: "Extracting",
  awaiting_review: "Awaiting Review",
  approved: "Approved",
  sent: "Sent",
  failed: "Failed",
};

const IN_PROGRESS: ProcessingState[] = ["queued", "downloading", "transcribing", "extracting"];

interface Props {
  upn: string;
  onClose: () => void;
}

export default function ImportModal({ upn, onClose }: Props) {
  const [recordings, setRecordings] = useState<AvailableRecording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Set<string>>(new Set());
  const [justImported, setJustImported] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAvailableRecordings(upn);
      setRecordings(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load recordings");
    } finally {
      setLoading(false);
    }
  }, [upn]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function handleImport(rec: AvailableRecording) {
    setBusy((prev) => new Set(prev).add(rec.drive_item_id));
    try {
      await importRecording(rec.drive_item_id, rec.drive_id, upn);
      setJustImported((prev) => new Set(prev).add(rec.drive_item_id));
      toast.success(`"${rec.name.replace(/\.mp4$/i, "")}" queued for processing`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy((prev) => { const s = new Set(prev); s.delete(rec.drive_item_id); return s; });
    }
  }

  async function handleReprocess(rec: AvailableRecording) {
    setBusy((prev) => new Set(prev).add(rec.drive_item_id));
    try {
      await reprocessRecording(rec.drive_item_id, rec.drive_id, upn);
      toast.success(`"${rec.name.replace(/\.mp4$/i, "")}" requeued for processing`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Retry failed");
    } finally {
      setBusy((prev) => { const s = new Set(prev); s.delete(rec.drive_item_id); return s; });
    }
  }

  function renderAction(rec: AvailableRecording) {
    const isBusy = busy.has(rec.drive_item_id);
    const state = rec.meeting_state;

    if (isBusy) {
      return (
        <span className="inline-flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
          <Loader2 size={13} className="animate-spin" /> Working…
        </span>
      );
    }

    if (!rec.already_imported || justImported.has(rec.drive_item_id)) {
      return (
        <button
          type="button"
          onClick={() => handleImport(rec)}
          className="inline-flex items-center gap-1.5 bg-[#003366] hover:bg-[#0a4a8c] text-white text-[12.5px] font-semibold px-3 py-1.5 rounded transition-colors"
        >
          <Download size={13} /> Transcribe
        </button>
      );
    }

    if (state === "failed") {
      return (
        <button
          type="button"
          onClick={() => handleReprocess(rec)}
          className="inline-flex items-center gap-1.5 bg-red-600 hover:bg-red-700 text-white text-[12.5px] font-semibold px-3 py-1.5 rounded transition-colors"
        >
          <RefreshCw size={13} /> Retry
        </button>
      );
    }

    if (state === "awaiting_review" && rec.meeting_id) {
      return (
        <Link
          href={`/meetings/${rec.meeting_id}`}
          onClick={onClose}
          className="inline-flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-[12.5px] font-semibold px-3 py-1.5 rounded transition-colors"
        >
          <ExternalLink size={13} /> Review
        </Link>
      );
    }

    if (state && IN_PROGRESS.includes(state)) {
      return (
        <span className="inline-flex items-center gap-1.5 text-blue-600 text-[12.5px] font-medium">
          <Loader2 size={13} className="animate-spin" /> {STATE_LABEL[state]}
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1 text-green-600 text-[12.5px] font-medium">
        <CheckCircle2 size={14} /> {state ? STATE_LABEL[state] : "Imported"}
      </span>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl overflow-hidden">
        <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-6 py-5 flex items-center justify-between">
          <div>
            <h2 className="text-white font-semibold text-[15px]">Process a Past Recording</h2>
            <p className="text-white/60 text-[13px] mt-0.5">
              Select an existing, untranscribed MP4 from your OneDrive Recordings folder
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-white/60 hover:text-white transition-colors">
            <X size={20} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <Loader2 size={28} className="animate-spin mb-3 text-[#003366]" />
              <p className="text-[13.5px]">Scanning your OneDrive…</p>
            </div>
          )}

          {error && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <AlertCircle size={36} className="mb-3 text-red-400" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">Could not load recordings</p>
              <p className="text-[12.5px] text-center max-w-xs">{error}</p>
              <button type="button" onClick={load} className="mt-4 text-[13px] text-[#003366] hover:underline font-medium">
                Try again
              </button>
            </div>
          )}

          {!loading && !error && recordings.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-[#6b7280]">
              <FolderOpen size={36} className="mb-3 text-[#dde1e8]" />
              <p className="text-[13.5px] font-semibold text-[#1a1a2e] mb-1">No recordings found</p>
              <p className="text-[12.5px]">Your OneDrive Recordings folder appears to be empty.</p>
            </div>
          )}

          {!loading && !error && recordings.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Recording", "Date", "Size", "Status", ""].map((h) => (
                    <th key={h} className="bg-[#f8fafc] text-[#374151] text-xs font-semibold px-4 py-2.5 text-left border-b border-[#dde1e8] first:pl-6 last:pr-6">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recordings.map((rec, i) => (
                  <tr key={rec.drive_item_id} className={i % 2 === 1 ? "bg-[#f8fafc]" : ""}>
                    <td className="px-4 py-3 pl-6 border-b border-[#dde1e8] font-medium text-[#1a1a2e] max-w-50">
                      <span className="block truncate text-[13px]" title={rec.name}>
                        {rec.name.replace(/\.mp4$/i, "")}
                      </span>
                      {rec.meeting_error && (
                        <span className="block text-[11px] text-red-500 truncate mt-0.5" title={rec.meeting_error}>
                          {rec.meeting_error}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      {formatDate(rec.created_at)}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                      {formatBytes(rec.size)}
                    </td>
                    <td className="px-4 py-3 border-b border-[#dde1e8] text-[12.5px]">
                      {rec.meeting_state ? (
                        <span className={`font-medium ${rec.meeting_state === "failed" ? "text-red-600" : rec.meeting_state === "awaiting_review" ? "text-amber-600" : "text-[#6b7280]"}`}>
                          {STATE_LABEL[rec.meeting_state]}
                        </span>
                      ) : "—"}
                    </td>
                    <td className="px-4 py-3 pr-6 border-b border-[#dde1e8] text-right whitespace-nowrap">
                      {renderAction(rec)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#dde1e8] flex items-center justify-between bg-[#f8fafc]">
          <p className="text-[12px] text-[#6b7280]">
            The transcript and AI notes will appear for organiser review once processing finishes.
          </p>
          <button type="button" onClick={onClose} className="text-[13px] font-medium text-[#003366] hover:underline">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
