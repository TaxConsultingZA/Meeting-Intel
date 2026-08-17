import { auth } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  const session = await auth();
  if (!session?.accessToken) return new Response(null, { status: 401 });

  try {
    const response = await fetch(`${API_BASE}/users/me/photo`, {
      headers: { Authorization: `Bearer ${session.accessToken}` },
      cache: "no-store",
    });
    if (!response.ok || response.status === 204) {
      return new Response(null, { status: 404, headers: { "Cache-Control": "private, max-age=300" } });
    }
    return new Response(await response.arrayBuffer(), {
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "image/jpeg",
        "Cache-Control": "private, max-age=3600",
      },
    });
  } catch {
    return new Response(null, { status: 404 });
  }
}
