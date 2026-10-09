import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Nav from "@/components/nav";
import ActionItemsClient from "./action-items-client";

export default async function ActionItemsPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  // No /users/me call: registration and welcome-email side effects are unnecessary here.
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} />
    <ActionItemsClient accessToken={session.accessToken} />
  </>;
}
