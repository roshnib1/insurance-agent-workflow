import type { Metadata } from "next";
import { Inter, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

/**
 * Two type roles, chosen for what this product actually is:
 *
 *  - Inter: the UI/reading face. Neutral, dense-friendly, disappears behind
 *    content -- appropriate for a screen a CRO or Senior Underwriter reads
 *    for long stretches.
 *  - IBM Plex Mono: the telemetry face. Used only for timestamps, run ids,
 *    tool/callback names, and the live event console -- the parts of the
 *    UI that are literally logs and traces, so they read like logs and
 *    traces (same instinct as Datadog / GitHub Actions log viewers).
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Commercial Property Underwriting AI Workflow",
  description:
    "Live visualization and control surface for the Commercial Property Underwriting multi-agent workflow.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${plexMono.variable} font-sans antialiased`}>
        {children}
      </body>
    </html>
  );
}
