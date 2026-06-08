import NextAuth from "next-auth";
import Resend from "next-auth/providers/resend";
import Credentials from "next-auth/providers/credentials";
import PostgresAdapter from "@auth/pg-adapter";
import { Pool } from "pg";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: process.env.DATABASE_URL?.includes("localhost")
    ? false
    : { rejectUnauthorized: false },
});

const providers = [];

if (process.env.AUTH_RESEND_KEY) {
  providers.push(
    Resend({
      from: process.env.EMAIL_FROM ?? "Meeting Intelligence <onboarding@resend.dev>",
    })
  );
}

if (process.env.NODE_ENV !== "production") {
  providers.push(
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
  );
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  adapter: PostgresAdapter(pool),
  providers,
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account }) {
      if (account?.provider === "resend") {
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
