import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMe, getAdminAccessRequests } from "@/lib/api";
import Nav from "@/components/nav";
import AdminClient from "./admin-client";

export default async function AdminPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");

  const upn = session.user.email;
  const accessToken = session.accessToken;
  const me = await getMe(accessToken).catch(() => null);

  if (!me) redirect("/");          // not registered at all
  if (!me.is_admin) redirect("/"); // registered but not admin

  // Access requests are the operational queue and are visible initially. The
  // three long, collapsed sections fetch their existing data only when opened.
  const processingRequests = await getAdminAccessRequests(accessToken).catch(() => []);

  return (
    <>
      <Nav userEmail={upn} accessToken={accessToken} isAdmin={true} />
      <AdminClient initialRequests={processingRequests} callerUpn={upn} accessToken={accessToken} />
    </>
  );
}
