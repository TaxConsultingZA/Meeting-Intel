import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMe } from "@/lib/api";
import Nav from "@/components/nav";
import ActionItemsClient from "./action-items-client";

export default async function ActionItemsPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  const me = await getMe(session.accessToken).catch(() => null);
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} isAdmin={me?.is_admin ?? false} />
    <ActionItemsClient accessToken={session.accessToken} />
  </>;
}
