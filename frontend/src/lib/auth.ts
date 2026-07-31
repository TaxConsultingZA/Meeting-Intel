import NextAuth from "next-auth";
import Resend from "next-auth/providers/resend";
import Credentials from "next-auth/providers/credentials";
import PostgresAdapter from "@auth/pg-adapter";
import { Pool } from "pg";

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

async function refreshAccessToken(token: any) {
  const response = await fetch(
    `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
    {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        client_id: process.env.AUTH_MICROSOFT_ENTRA_ID_ID ?? "",
        client_secret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET ?? "",
        grant_type: "refresh_token",
        refresh_token: token.refreshToken,
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
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET,
      issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`,
      checks: ["pkce", "state"], 
      authorization: {
        url: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize`,
        params: { 
          scope: `openid profile email offline_access api://${apiClientId}/access_as_user`,
        },
      },
      token: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
      profile(profile: any) {
        return {
          id: profile.sub,
          name: profile.name || profile.preferred_username,
          email: profile.email || profile.preferred_username,
          image: profile.picture,
        };
      },
    },
    ...(process.env.AUTH_RESEND_KEY ? [
      Resend({
        from: process.env.EMAIL_FROM ?? "Meeting Intelligence <onboarding@resend.dev>",
      })
    ] : []),
    ...(process.env.NODE_ENV !== "production" ? [
      Credentials({
        id: "dev-login",
        name: "Dev Login",
        credentials: { email: { label: "Email", type: "email" } },
        async authorize(credentials) {
          const email = credentials?.email as string | undefined;
          if (!email) return null;
          return { id: email, email, name: email.split("@")[0] };
        },
      })
    ] : [])
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account }) {
      // Backend trust model: We only allow users from the verified domain
      if (account?.provider === "resend" || account?.provider === "microsoft-entra-id") {
        return user.email?.toLowerCase().endsWith("@taxconsulting.co.za") ?? false;
      }
      return true;
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
        process.env.NODE_ENV !== "production" &&
        user?.email &&
        account?.provider !== "microsoft-entra-id"
      ) {
        token.accessToken = `mock:${user.email.toLowerCase()}`;
        token.accessTokenExpires = Number.MAX_SAFE_INTEGER;
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
