import type { Metadata } from "next";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meeting Intelligence — TaxConsulting SA",
  description: "Review and approve AI-extracted meeting notes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full bg-[#F0F2F5]">
        {children}
        <Toaster richColors position="bottom-right" />
      </body>
    </html>
  );
}
