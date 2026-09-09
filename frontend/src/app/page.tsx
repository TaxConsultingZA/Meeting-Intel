import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMe } from "@/lib/api";
import Nav from "@/components/nav";
import DashboardClient from "./dashboard-client";
import PendingAccess from "@/components/pending-access";
import SubscriptionGate from "@/components/subscription-gate";

export default async function DashboardPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");

  const upn = session.user.email;
  const accessToken = session.accessToken;

  // Check if the user is registered — unregistered domain users see the pending screen.
  // /users/me auto-registers valid company users on their first Entra login.
  // Do not turn backend/network failures into a misleading "Access Pending" page.
  const me = await getMe(accessToken);
  if (!me) {
    return <PendingAccess userEmail={upn} />;
  }
  return (
    <>
      <Nav userEmail={upn} accessToken={accessToken} isAdmin={me.is_admin} />
      {!me.is_subscribed && (
        <SubscriptionGate userEmail={upn} accessToken={accessToken} />
      )}
      <DashboardClient
        meetings={[]}
        upcoming={[]}
        historical={[]}
        recordingJobs={[]}
        syncStates={[]}
        loadErrors={[]}
        upn={upn}
        accessToken={accessToken}
        isSubscribed={me.is_subscribed}
        deferInitialLoad
      />
    </>
  );
}
