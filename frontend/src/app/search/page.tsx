import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMe } from "@/lib/api";
import Nav from "@/components/nav";
import SearchClient from "./search-client";

export default async function SearchPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  const me = await getMe(session.accessToken).catch(() => null);
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} isAdmin={me?.is_admin ?? false} />
    <SearchClient key={session.accessToken} accessToken={session.accessToken} />
  </>;
}
