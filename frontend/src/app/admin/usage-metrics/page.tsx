import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/lib/auth";
import { getMe } from "@/lib/api";
import { redirect } from "next/navigation";
import UsageMetricsChart from "../usage-metrics";
import "../admin-workspace.css";

function MetricsPage({ token }: { token: string }) {
  return <main className="usage-page max-w-6xl mx-auto px-4 sm:px-6 py-5">
    <header className="usage-page-header">
      <div><h1>Usage Metrics</h1><p>Explore durable activity by Johannesburg date and Business Unit.</p></div>
      <Link href="/admin" className="admin-metrics-link"><ArrowLeft size={16} aria-hidden="true" /> Admin workspace</Link>
    </header>
    <UsageMetricsChart token={token} />
  </main>;
}

export default async function UsageMetricsPage() {
  const session = await auth();
  if (!session?.user?.email || !session.accessToken || session.authError) redirect("/login");
  if (!(await getMe(session.accessToken).catch(() => null))?.is_admin) redirect("/");
  return <MetricsPage token={session.accessToken} />;
}
