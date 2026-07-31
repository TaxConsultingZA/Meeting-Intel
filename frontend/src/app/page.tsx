import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getAllMeetings, getUpcomingMeetings, getMe, getHistoricalMeetings } from "@/lib/api";
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
  const me = await getMe(accessToken).catch(() => null);
  if (!me) {
    return <PendingAccess userEmail={upn} />;
  }
  if (!me.is_subscribed) {
    return (
      <>
        <Nav userEmail={upn} accessToken={accessToken} isAdmin={me.is_admin} />
        <SubscriptionGate userEmail={upn} accessToken={accessToken} />
      </>
    );
  }

  const [meetings, upcoming, historical] = await Promise.all([
    getAllMeetings(accessToken).catch(() => []),
    getUpcomingMeetings(accessToken).catch(() => []),
    getHistoricalMeetings(accessToken).catch(() => []),
  ]);

  return (
    <>
      <Nav userEmail={upn} accessToken={accessToken} isAdmin={me.is_admin} />
      <DashboardClient meetings={meetings} upcoming={upcoming} historical={historical} upn={upn} accessToken={accessToken} />
    </>
  );
}
