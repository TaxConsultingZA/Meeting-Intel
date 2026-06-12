"use client";
import { useState } from "react";
import { signIn } from "next-auth/react";

const HAS_RESEND = process.env.NEXT_PUBLIC_HAS_RESEND === "true";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email) return;
    setLoading(true);
    setError("");

    if (HAS_RESEND) {
      const result = await signIn("resend", { email, callbackUrl: "/", redirect: false });
      setLoading(false);
      if (result?.error) {
        setError("Could not send the link. Please try again.");
      } else {
        setSent(true);
      }
    } else {
      await signIn("dev-login", { email, callbackUrl: "/" });
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#F0F2F5] flex items-center justify-center">
      <div className="bg-white rounded-lg border border-[#dde1e8] shadow-md overflow-hidden w-full max-w-sm">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-8 py-7 text-center">
          <div className="inline-flex items-center gap-3 mb-1">
            <div className="w-10 h-10 bg-[#C9A52C] rounded-lg flex items-center justify-center font-extrabold text-[#003366] text-base">
              MI
            </div>
            <span className="text-white font-semibold text-lg">
              Tax<span className="text-[#C9A52C]">Consulting</span> SA
            </span>
          </div>
          <p className="text-white/60 text-sm mt-2">Meeting Intelligence</p>
        </div>

        <div className="px-8 py-8">
          {sent ? (
            <div className="text-center">
              <div className="w-12 h-12 bg-[#003366]/10 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#003366" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
              </div>
              <p className="text-[#111827] font-semibold text-sm mb-1">Check your inbox</p>
              <p className="text-[#6b7280] text-sm">
                We sent a sign-in link to <span className="font-medium text-[#003366]">{email}</span>.
                Click the link to continue.
              </p>
              <button
                type="button"
                onClick={() => { setSent(false); setEmail(""); }}
                className="mt-5 text-xs text-[#6b7280] underline underline-offset-2 hover:text-[#003366]"
              >
                Use a different email
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              <button
                type="button"
                onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/" })}
                className="w-full flex items-center justify-center gap-3 bg-white border border-[#dde1e8] hover:bg-gray-50 text-[#374151] font-semibold py-2.5 px-4 rounded-md text-sm transition-colors shadow-sm"
              >
                <svg width="20" height="20" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
                  <path d="M1 1h9v9H1z" fill="#f25022"/><path d="M11 1h9v9h-9z" fill="#7fbb00"/><path d="M1 11h9v9H1z" fill="#00a4ef"/><path d="M11 11h9v9h-9z" fill="#ffb900"/>
                </svg>
                Sign in with Microsoft
              </button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t border-[#dde1e8]"></span>
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-white px-2 text-[#9ca3af]">Or continue with email</span>
                </div>
              </div>

              <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                <p className="text-[#6b7280] text-xs text-center">
                  Enter your work email and we&apos;ll send you a sign-in link.
                </p>
                <div>
                  <label htmlFor="email" className="block text-xs font-semibold text-[#374151] mb-1">
                    Work email
                  </label>
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@taxconsulting.co.za"
                    className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#003366] focus:border-transparent"
                  />
                </div>
                {error && (
                  <p className="text-red-500 text-xs">{error}</p>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-[#003366] hover:bg-[#0a4a8c] disabled:opacity-60 text-white font-semibold py-2.5 px-4 rounded-md text-sm transition-colors"
                >
                  {loading ? "Sending…" : "Send sign-in link"}
                </button>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
