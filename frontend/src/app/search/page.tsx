import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Nav from "@/components/nav";
import SearchClient from "./search-client";

export default async function SearchPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} />
    <SearchClient key={session.accessToken} accessToken={session.accessToken} />
  </>;
}
