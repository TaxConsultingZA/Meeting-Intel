import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getAllMeetings, getUpcomingMeetings, getMe, getHistoricalMeetings, getSyncStatus } from "@/lib/api";
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
  async function load<T>(promise: Promise<T>, label: string, fallback: T) {
    try {
      return { data: await promise, error: null as string | null };
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unknown error";
      return { data: fallback, error: `${label}: ${detail}` };
    }
  }

  const [meetingResult, upcomingResult, historicalResult, syncResult] = await Promise.all([
    load(getAllMeetings(accessToken), "Meeting records could not be loaded", []),
    me.is_subscribed
      ? load(getUpcomingMeetings(accessToken), "Calendar sync failed", [])
      : Promise.resolve({ data: [], error: null }),
    load(getHistoricalMeetings(accessToken), "Historical meetings could not be loaded", []),
    load(getSyncStatus(accessToken), "Sync status could not be loaded", []),
  ]);

  return (
    <>
      <Nav userEmail={upn} accessToken={accessToken} isAdmin={me.is_admin} />
      {!me.is_subscribed && (
        <SubscriptionGate userEmail={upn} accessToken={accessToken} />
      )}
      <DashboardClient
        meetings={meetingResult.data}
        upcoming={upcomingResult.data}
        historical={historicalResult.data}
        syncStates={syncResult.data}
        loadErrors={[meetingResult.error, upcomingResult.error, historicalResult.error, syncResult.error].filter((value): value is string => Boolean(value))}
        upn={upn}
        accessToken={accessToken}
        isSubscribed={me.is_subscribed}
      />
    </>
  );
}
