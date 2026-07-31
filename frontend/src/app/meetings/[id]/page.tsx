import { auth } from "@/lib/auth";
import { redirect, notFound } from "next/navigation";
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
  const meeting = await getMeeting(id, session.accessToken).catch(() => null);
  if (!meeting) notFound();

  return (
    <>
      <Nav userEmail={upn} accessToken={session.accessToken} />
      <MeetingDetailClient meeting={meeting} upn={upn} accessToken={session.accessToken} />
    </>
  );
}
