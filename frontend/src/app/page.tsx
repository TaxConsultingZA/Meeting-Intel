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
  let me;
  try {
    me = await getMe(accessToken);
  } catch {
    return (
      <main className="min-h-screen bg-[#f0f4ff] flex items-center justify-center px-4">
        <div role="alert" className="w-full max-w-md rounded-xl bg-white p-8 text-center shadow-lg">
          <h1 className="text-lg font-bold text-[#003366]">Service unavailable</h1>
          <p className="mt-2 text-sm text-[#6b7280]">Unable to load account. Please try again shortly.</p>
        </div>
      </main>
    );
  }
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
