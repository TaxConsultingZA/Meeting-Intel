import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMeeting } from "@/lib/api";
import Nav from "@/components/nav";
import MeetingDetailClient from "./meeting-detail-client";

export default async function MeetingDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");

  const { id } = await params;
  const upn = session.user.email;
  let meeting;
  try {
    meeting = await getMeeting(id, session.accessToken);
  } catch {
    return (
      <main className="min-h-screen bg-[#f0f4ff] flex items-center justify-center px-4">
        <div role="alert" className="w-full max-w-md rounded-xl bg-white p-8 text-center shadow-lg">
          <h1 className="text-lg font-bold text-[#003366]">Meeting unavailable</h1>
          <p className="mt-2 text-sm text-[#6b7280]">Unable to load this meeting right now. Please try again shortly.</p>
        </div>
      </main>
    );
  }

  return (
    <>
      <Nav userEmail={upn} accessToken={session.accessToken} />
      <MeetingDetailClient meeting={meeting} upn={upn} accessToken={session.accessToken} />
    </>
  );
}
