"use client";

import MeetingPageError from "@/components/meeting-page-error";

export default function Error({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return <MeetingPageError page="search" retry={retry} />;
}
