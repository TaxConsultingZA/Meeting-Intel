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

export const { handlers, signIn, signOut, auth } = NextAuth({
  // 2. Re-enable the Database Adapter for persistent sessions
  adapter: PostgresAdapter(pool),
  providers: [
    // 3. Custom OAuth config for Azure AD to bypass OIDC issuer mismatch (v1 vs v2 tokens)
    {
      id: "microsoft-entra-id",
      name: "Microsoft Entra ID",
      type: "oauth", 
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
      // Public Client: No clientSecret provided.
      checks: ["pkce", "state"], 
      authorization: {
        url: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/authorize`,
        params: { 
          scope: "openid profile email User.Read",
          redirect_uri: "http://localhost:3000/authentication/login-callback"
        },
      },
      token: {
        url: `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
        params: { 
          redirect_uri: "http://localhost:3000/authentication/login-callback"
        }
      },
      userinfo: "https://graph.microsoft.com/oidc/userinfo",
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
    async jwt({ token, user }) {
      if (user?.email) token.email = user.email;
      if (user?.name) token.name = user.name;
      return token;
    },
    async session({ session, token }) {
      return {
        ...session,
        user: {
          ...session.user,
          email: (token.email as string) ?? session.user?.email,
          name: (token.name as string) ?? session.user?.name,
        },
      };
    },
  },
  pages: { signIn: "/login" },
});
