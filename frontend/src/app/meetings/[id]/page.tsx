import { Suspense } from "react";
import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { getMeeting } from "@/lib/api";
import Nav from "@/components/nav";
import MeetingDetailClient from "./meeting-detail-client";
import MeetingDetailLoading from "./loading";
import MeetingLoadError from "./meeting-load-error";

async function MeetingContent({ id, upn, accessToken }: { id: string; upn: string; accessToken: string }) {
  let meeting;
  try {
    meeting = await getMeeting(id, accessToken);
  } catch {
    return <MeetingLoadError />;
  }
  return <MeetingDetailClient meeting={meeting} upn={upn} accessToken={accessToken} />;
}

export default async function MeetingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  const { id } = await params;
  return <>
    <Nav userEmail={session.user.email} accessToken={session.accessToken} />
    <Suspense fallback={<MeetingDetailLoading showNavigation={false} />}>
      <MeetingContent id={id} upn={session.user.email} accessToken={session.accessToken} />
    </Suspense>
  </>;
}
