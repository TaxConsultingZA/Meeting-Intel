"use client";
import { formatDateTime } from "@/lib/time";

export function useUserTimeZone() {
  return "Africa/Johannesburg";
}

export default function LocalDateTime({ value, unavailable = "—" }: { value?: string | null; unavailable?: string }) {
  const zone = useUserTimeZone();
  return <span>{value ? formatDateTime(value, zone) : unavailable}</span>;
}
