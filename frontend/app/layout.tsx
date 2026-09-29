import type { Metadata } from "next";
import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";
import { Navigation } from "@/components/navigation";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "TenderScout · Procurement Intelligence",
    template: "%s · TenderScout",
  },
  description:
    "Procurement intelligence, tender discovery and explainable company matching.",
};

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="11"
        cy="11"
        r="6.5"
        stroke="currentColor"
        strokeWidth="1.7"
      />
      <path
        d="m16 16 4 4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M6.5 9.5a5.5 5.5 0 0 1 11 0v3.2l1.4 2.8H5.1l1.4-2.8V9.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M10 18a2.2 2.2 0 0 0 4 0"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CrownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="m4 7 4 4 4-6 4 6 4-4-2 11H6L4 7Z"
        fill="currentColor"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>

        <aside className="sidebar">
          <Link href="/" className="brand premium-brand">
            <BrandLogo />
          </Link>

          <p className="nav-caption">YOUR WORKSPACE</p>

          <Navigation />

          <div className="sidebar-upgrade">
            <span className="sidebar-upgrade-icon">
              <CrownIcon />
            </span>

            <div>
              <strong>TenderScout Pro</strong>
              <span>More intelligence tools</span>
            </div>

            <span className="sidebar-upgrade-arrow">›</span>
          </div>
        </aside>

        <div className="workspace">
          <header className="topbar">
            <form
              className="topbar-search"
              action="/discover"
            >
              <SearchIcon />

              <input
                type="search"
                name="q"
                minLength={3}
                maxLength={255}
                placeholder="Search tenders, keywords, organisations..."
                aria-label="Search tenders"
              />
            </form>

            <div className="topbar-actions">
              <Link
                href="/alerts"
                className="topbar-icon-button"
                aria-label="Notifications"
              >
                <BellIcon />
                <span className="notification-indicator" />
              </Link>

              <span
                className="topbar-avatar"
                aria-label="Workspace profile"
              >
                A
              </span>
            </div>
          </header>

          <main id="main">{children}</main>
        </div>
      </body>
    </html>
  );
}