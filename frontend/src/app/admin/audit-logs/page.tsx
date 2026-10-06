import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMe } from "@/lib/api";
import Nav from "@/components/nav";
import AuditLogsClient from "./audit-logs-client";

export default async function AuditLogsPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  const me = await getMe(session.accessToken).catch(() => null);
  if (!me?.is_admin) redirect("/");
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} isAdmin />
    <AuditLogsClient accessToken={session.accessToken} />
  </>;
}
