"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import NotificationBell from "@/components/notification-bell";

interface NavProps {
  userEmail: string;
  accessToken: string;
  isAdmin?: boolean;
}

export default function Nav({ userEmail, accessToken, isAdmin }: NavProps) {
  const path = usePathname();
  const initials = userEmail
    .split("@")[0]
    .split(".")
    .map((p) => p[0]?.toUpperCase() ?? "")
    .slice(0, 2)
    .join("");

  return (
    <nav className="bg-[#003366] h-14 flex items-center px-6 gap-8 sticky top-0 z-50 shadow-md">
      <Link href="/" className="flex items-center gap-2.5 shrink-0">
        <div className="w-8 h-8 bg-[#C9A52C] rounded-md flex items-center justify-center font-extrabold text-[#003366] text-sm">
          MI
        </div>
        <span className="text-white font-semibold text-[15px]">
          Tax<span className="text-[#C9A52C]">Consulting</span> SA
        </span>
      </Link>

      <div className="flex gap-1 ml-2">
        {[
          { href: "/", label: "Dashboard" },
          ...(isAdmin ? [{ href: "/admin", label: "Admin" }] : []),
        ].map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "px-3.5 py-1.5 rounded-md text-[13.5px] transition-colors",
              path === href
                ? "text-[#C9A52C] bg-white/10"
                : "text-white/70 hover:text-white hover:bg-white/10",
            )}
          >
            {label}
          </Link>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-3">
        <span className="text-white/60 text-[13px] hidden sm:block">
          {userEmail}
        </span>
        <NotificationBell upn={accessToken} />
        <div className="w-8 h-8 rounded-full bg-[#C9A52C] flex items-center justify-center text-[#003366] font-bold text-xs">
          {initials}
        </div>
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="text-white/50 hover:text-white transition-colors"
          title="Sign out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </nav>
  );
}
