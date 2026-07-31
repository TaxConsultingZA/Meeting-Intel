import "next-auth";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    authError?: string;
  }
}

declare module "@auth/core/jwt" {
  interface JWT {
    accessToken?: string;
    accessTokenExpires?: number;
    refreshToken?: string;
    authError?: string;
  }
}
