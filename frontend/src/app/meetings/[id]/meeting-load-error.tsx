"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

export default function MeetingLoadError() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return <main className="mx-auto max-w-6xl px-6 py-7">
    <Link href="/" className="text-sm text-[#003366] underline">Back to Dashboard</Link>
    <h1 className="mt-4 text-xl font-semibold text-[#003366]">Meeting details</h1>
    <div role="alert" className="mt-5 rounded-lg border border-amber-200 bg-white p-5">
      <h2 className="font-semibold text-[#003366]">Meeting unavailable</h2>
      <p className="mt-2 text-sm text-[#6b7280]">We could not load this meeting. Check your connection and try again. If this continues, check your access with an administrator.</p>
      <button type="button" disabled={pending} onClick={() => startTransition(() => router.refresh())} className="mt-4 rounded-md border border-[#003366] px-4 py-2 text-sm font-semibold text-[#003366] disabled:opacity-50">{pending ? "Loading meeting…" : "Retry loading meeting"}</button>
    </div>
  </main>;
}
