"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleMicrosoftSignIn() {
    setLoading(true);
    setError("");
    try {
      const result = await signIn("microsoft-entra-id", {
        callbackUrl: "/",
        redirect: false,
      });
      if (!result?.url) throw new Error("Microsoft did not return a sign-in URL");
      window.location.assign(result.url);
    } catch {
      setError("Microsoft sign-in could not start. Please try again.");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#F0F2F5] flex items-center justify-center px-4">
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
          <h1 className="text-[#111827] font-semibold text-lg text-center">Company sign-in</h1>
          <p className="text-[#6b7280] text-sm text-center mt-2 mb-6 leading-6">
            Sign in with your TaxConsulting Microsoft account. Calendar and OneDrive
            processing starts only after you opt in.
          </p>
          <button
            type="button"
            disabled={loading}
            onClick={handleMicrosoftSignIn}
            className="w-full flex items-center justify-center gap-3 bg-white border border-[#dde1e8] hover:bg-gray-50 text-[#374151] font-semibold py-2.5 px-4 rounded-md text-sm transition-colors shadow-sm disabled:opacity-60"
          >
            <svg width="20" height="20" viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M1 1h9v9H1z" fill="#f25022" />
              <path d="M11 1h9v9h-9z" fill="#7fbb00" />
              <path d="M1 11h9v9H1z" fill="#00a4ef" />
              <path d="M11 11h9v9h-9z" fill="#ffb900" />
            </svg>
            {loading ? "Redirecting to Microsoft..." : "Sign in with Microsoft"}
          </button>
          {error && <p className="mt-3 text-center text-sm text-red-600">{error}</p>}
          <p className="mt-5 text-center text-xs text-[#9ca3af]">
            Only @taxconsulting.co.za accounts are accepted.
          </p>
        </div>
      </div>
    </div>
  );
}
