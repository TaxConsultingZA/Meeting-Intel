"use client";

import { useState, useTransition } from "react";
import { MeetingPageHeading, MeetingPageNavigation, meetingPages, type MeetingPage } from "./meeting-page-feedback";

export default function MeetingPageError({ page, retry }: { page: MeetingPage; retry: () => void }) {
  const [pending, startTransition] = useTransition();
  const [attempted, setAttempted] = useState(false);
  return <><MeetingPageNavigation page={page} />
    <main className={`mx-auto min-w-0 ${meetingPages[page].width} px-4 py-8 sm:px-6`}>
      <MeetingPageHeading page={page} />
      <div role="alert" className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">
        <p>This page could not be loaded. Please try again.</p>
        <button disabled={pending} onClick={() => { setAttempted(true); startTransition(() => retry()); }} className="mt-3 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-semibold">{pending ? "Retrying…" : "Try again"}</button>
        {attempted && !pending && <p className="mt-2 text-sm">If the problem continues, try again in a moment.</p>}
      </div>
    </main>
  </>;
}
