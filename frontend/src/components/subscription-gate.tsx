"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarCheck, ShieldCheck } from "lucide-react";
import { subscribeCurrentUser } from "@/lib/api";

/**
 * Non-blocking opt-in notice. Company users may browse the application before
 * subscribing, but Calendar/OneDrive processing starts only after this choice.
 */
export default function SubscriptionGate({
  userEmail,
  accessToken,
}: {
  userEmail: string;
  accessToken: string;
}) {
  const router = useRouter();
  const [subscribing, setSubscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function subscribe() {
    setSubscribing(true);
    setError(null);
    try {
      await subscribeCurrentUser(accessToken);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not activate subscription");
    } finally {
      setSubscribing(false);
    }
  }

  return (
    <section className="max-w-5xl mx-auto px-6 pt-6">
      <div className="bg-[#fffaf0] border border-[#C9A52C]/60 rounded-xl shadow-sm px-5 py-4 flex flex-col lg:flex-row lg:items-center gap-4">
        <div className="w-10 h-10 rounded-full bg-[#C9A52C] flex items-center justify-center shrink-0">
          <CalendarCheck size={20} className="text-[#003366]" />
        </div>
        <div className="flex-1">
          <h2 className="text-[#003366] font-bold text-[15px]">Automatic meeting notes are off</h2>
          <p className="text-[#4b5563] text-[13px] leading-5 mt-1">
            You can browse the app now. Opt in once to let Meeting Intelligence process
            your Outlook calendar and OneDrive recordings for future meeting notes.
          </p>
          <p className="text-[#6b7280] text-[11.5px] mt-1 flex items-center gap-1">
            <ShieldCheck size={13} /> {userEmail} · You review before anything is sent, and you can opt out later.
          </p>
          {error && <p className="text-sm text-red-700 mt-2">{error}</p>}
        </div>
        <button
          type="button"
          onClick={subscribe}
          disabled={subscribing}
          className="shrink-0 bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] text-[13px] font-bold px-5 py-2.5 rounded-md disabled:opacity-60"
        >
          {subscribing ? "Activating..." : "Opt in to meeting notes"}
        </button>
      </div>
    </section>
  );
}
