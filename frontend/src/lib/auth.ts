import NextAuth from "next-auth";
import type { JWT } from "next-auth/jwt";
import PostgresAdapter from "@auth/pg-adapter";
import { Pool } from "pg";
import { appendFileSync } from "node:fs";

// 1. Sanitize Database URL for pg (remove SQLAlchemy driver prefix)
const connectionString = process.env.DATABASE_URL?.replace("postgresql+asyncpg://", "postgresql://");

const pool = new Pool({
  connectionString,
  ssl: connectionString?.includes("localhost")
    ? false
    : { rejectUnauthorized: false },
});

const tenantId = process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID;
const apiClientId =
  process.env.AUTH_MICROSOFT_ENTRA_ID_API_ID ??
  process.env.AUTH_MICROSOFT_ENTRA_ID_ID;

function safeErrorDetails(value: unknown, depth = 0): unknown {
  if (depth > 3 || value == null) return undefined;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value !== "object") return undefined;

  const blocked = /token|secret|password|authorization|cookie|state|verifier|^code$/i;
  const details: Record<string, unknown> = {};
  if (value instanceof Error) {
    details.name = value.name;
    details.message = value.message;
  }
  for (const key of Object.getOwnPropertyNames(value)) {
    if (blocked.test(key) || ["name", "message", "stack"].includes(key)) continue;
    const nested = safeErrorDetails((value as Record<string, unknown>)[key], depth + 1);
    if (nested !== undefined) details[key] = nested;
  }
  return details;
}

function recordAuthError(error: Error) {
  const record = {
    time: new Date().toISOString(),
    type: error.name,
    message: error.message,
    details: safeErrorDetails(error.cause),
  };
  console.error("[auth-error]", record);
  if (process.env.AUTH_ERROR_LOG) {
    appendFileSync(process.env.AUTH_ERROR_LOG, `${JSON.stringify(record)}\n`, "utf8");
  }
}
async function refreshAccessToken(token: JWT) {
  const response = await fetch(
    `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: process.env.AUTH_MICROSOFT_ENTRA_ID_ID ?? "",
        client_secret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET ?? "",
        grant_type: "refresh_token",
        refresh_token: token.refreshToken ?? "",
        scope: `openid profile email offline_access api://${apiClientId}/access_as_user`,
      }),
    },
  );
  const refreshed = await response.json();
  if (!response.ok) throw refreshed;
  return {
    ...token,
    accessToken: refreshed.access_token,
    accessTokenExpires: Date.now() + Number(refreshed.expires_in ?? 3600) * 1000,
    refreshToken: refreshed.refresh_token ?? token.refreshToken,
    authError: undefined,
  };
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  logger: { error: recordAuthError },
  // Versioned cookie name prevents sessions encrypted with an older local
  // AUTH_SECRET from breaking the new Entra configuration.
  cookies: {
    sessionToken: {
      name: "meeting-intel.session-token.v2",
      options: {
        httpOnly: true,
        sameSite: "lax",
        path: "/",
        secure: process.env.NODE_ENV === "production",
      },
    },
  },
  // 2. Re-enable the Database Adapter for persistent sessions
  adapter: PostgresAdapter(pool),
  providers: [
    // 3. Custom OAuth config for Azure AD to bypass OIDC issuer mismatch (v1 vs v2 tokens)
    {
      id: "microsoft-entra-id",
      name: "Microsoft Entra ID",
      type: "oidc",
      idToken: true,
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
      // The Entra registration uses the Web platform, so Auth.js performs the
      // authorization-code token exchange as a confidential client.
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET,
      // The Entra app registration changed during local setup. Within this
      // single verified tenant, safely reconnect an existing company email to
      // the new provider subject instead of rejecting it as a different login.
      allowDangerousEmailAccountLinking: true,
      issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`,
      checks: ["pkce", "state"], 
      authorization: {
        url: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize`,
        params: { 
          scope: `openid profile email offline_access api://${apiClientId}/access_as_user`,
          prompt: "select_account",
        },
      },
      token: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
      profile(profile: Record<string, unknown>) {
        const sub = typeof profile.sub === "string" ? profile.sub : "";
        const preferredUsername =
          typeof profile.preferred_username === "string" ? profile.preferred_username : "";
        return {
          id: sub,
          name: typeof profile.name === "string" ? profile.name : preferredUsername,
          email: typeof profile.email === "string" ? profile.email : preferredUsername,
          image: typeof profile.picture === "string" ? profile.picture : null,
        };
      },
    },
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account }) {
      // Backend trust model: We only allow users from the verified domain
      return account?.provider === "microsoft-entra-id" &&
        (user.email?.toLowerCase().endsWith("@taxconsulting.co.za") ?? false);
    },
    async jwt({ token, user, account }) {
      if (user?.email) token.email = user.email;
      if (user?.name) token.name = user.name;
      if (account?.provider === "microsoft-entra-id") {
        token.accessToken = account.access_token;
        token.accessTokenExpires = Number(account.expires_at ?? 0) * 1000;
        token.refreshToken = account.refresh_token;
        return token;
      }
      if (
        token.accessToken &&
        Date.now() < Number(token.accessTokenExpires ?? 0) - 60_000
      ) {
        return token;
      }
      if (!token.refreshToken) return { ...token, authError: "RefreshAccessTokenError" };
      try {
        return await refreshAccessToken(token);
      } catch {
        return { ...token, authError: "RefreshAccessTokenError" };
      }
    },
    async session({ session, token }) {
      return {
        ...session,
        user: {
          ...session.user,
          email: (token.email as string) ?? session.user?.email,
          name: (token.name as string) ?? session.user?.name,
        },
        accessToken: token.accessToken as string | undefined,
        authError: token.authError as string | undefined,
      };
    },
  },
  pages: { signIn: "/login" },
});
