"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarCheck, Database, ShieldCheck } from "lucide-react";
import { subscribeCurrentUser } from "@/lib/api";

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
    <main className="max-w-2xl mx-auto px-6 py-12">
      <div className="bg-white border border-[#dde1e8] rounded-xl shadow-sm overflow-hidden">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-7 py-6">
          <h1 className="text-white text-xl font-bold">Activate Meeting Intelligence</h1>
          <p className="text-white/70 text-sm mt-1">{userEmail}</p>
        </div>
        <div className="p-7">
          <p className="text-[#1a1a2e] text-sm leading-6">
            Nothing is monitored until you choose to subscribe. After this one-time
            opt-in, the service can automatically check your Outlook calendar and
            OneDrive Recordings folder for meetings that need processing.
          </p>
          <div className="grid sm:grid-cols-3 gap-3 my-6">
            {[
              [CalendarCheck, "Calendar", "Find scheduled Teams meetings"],
              [Database, "OneDrive", "Detect new meeting recordings"],
              [ShieldCheck, "Human review", "You approve before anything is sent"],
            ].map(([Icon, title, copy]) => {
              const C = Icon as typeof CalendarCheck;
              return (
                <div key={String(title)} className="border border-[#dde1e8] rounded-lg p-4">
                  <C size={19} className="text-[#C9A52C] mb-2" />
                  <div className="text-sm font-bold text-[#003366]">{String(title)}</div>
                  <div className="text-xs text-[#6b7280] mt-1 leading-5">{String(copy)}</div>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-[#6b7280] leading-5 mb-5">
            You can opt out later. Opting out stops future background checks; it
            does not silently delete meeting notes you already approved.
          </p>
          {error && <p className="text-sm text-red-700 mb-3">{error}</p>}
          <button
            type="button"
            onClick={subscribe}
            disabled={subscribing}
            className="w-full bg-[#C9A52C] hover:bg-[#e8c84a] text-[#003366] font-bold py-3 rounded-md disabled:opacity-60"
          >
            {subscribing ? "Activating…" : "Subscribe and start automatic processing"}
          </button>
        </div>
      </div>
    </main>
  );
}
