"use client";
import { formatDateTime, parseInstant } from "@/lib/time";

export function useUserTimeZone() {
  return "Africa/Johannesburg";
}

export default function LocalDateTime({ value, unavailable = "—" }: { value?: string | null; unavailable?: string }) {
  const zone = useUserTimeZone();
  return <span>{parseInstant(value) ? `${formatDateTime(value, zone)} SAST` : unavailable}</span>;
}
