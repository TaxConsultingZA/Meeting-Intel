import { handlers } from "@/lib/auth";
import { NextRequest } from "next/server";

/**
 * Custom callback handler to satisfy Azure AD's strict Redirect URI requirements.
 * It receives the callback at /authentication/login-callback and proxies it 
 * to the internal NextAuth handler at /api/auth/callback/microsoft-entra-id.
 */
export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  url.pathname = "/api/auth/callback/microsoft-entra-id";
  
  // Create a synthetic request that looks like the standard callback
  const internalReq = new NextRequest(url, {
    headers: req.headers,
    method: "GET",
  });

  return handlers.GET(internalReq);
}

export async function POST(req: NextRequest) {
  const url = new URL(req.url);
  url.pathname = "/api/auth/callback/microsoft-entra-id";
  
  const internalReq = new NextRequest(url, {
    headers: req.headers,
    method: "POST",
    body: req.body,
  });

  return handlers.POST(internalReq);
}
