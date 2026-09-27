import type { Metadata } from "next";
import Link from "next/link";
import { Navigation } from "@/components/navigation";
import "./globals.css";
export const metadata: Metadata = {
  title: {
    default: "TenderScout AI · Procurement intelligence",
    template: "%s · TenderScout AI",
  },
  description: "Procurement records, source evidence and explainable matching.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <aside className="sidebar">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              T
            </span>
            <span>
              TenderScout <small>AI</small>
            </span>
          </Link>
          <p className="nav-caption">YOUR WORKSPACE</p>
          <Navigation />
          <div className="sidebar-foot">
            <span className="dot" /> Procurement intelligence
            <p>Source facts. Clear provenance.</p>
          </div>
        </aside>
        <div className="workspace">
          <div className="topbar">
            <span>Procurement intelligence</span>
            <span className="workspace-label">TenderScout AI</span>
          </div>
          <main id="main">{children}</main>
          <footer className="footer">
            TenderScout AI{" "}
            <span>
              Review source documents before making procurement decisions.
            </span>
          </footer>
        </div>
      </body>
    </html>
  );
}
