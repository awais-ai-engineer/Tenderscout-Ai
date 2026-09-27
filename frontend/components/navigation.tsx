"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview", icon: "overview" },
  { href: "/discover", label: "Discover", icon: "discover" },
  { href: "/matches", label: "My Matches", icon: "matches" },
  { href: "/saved", label: "Saved Tenders", icon: "saved" },
  { href: "/companies", label: "Companies", icon: "companies" },
  { href: "/alerts", label: "Alerts", icon: "alerts" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;

function NavIcon({ name }: { name: (typeof links)[number]["icon"] }) {
  const paths = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    discover: <><circle cx="11" cy="11" r="7" /><path d="m16 16 5 5" /></>,
    matches: <path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" />,
    saved: <path d="M5 3h14v18l-7-4-7 4z" />,
    companies: <><rect x="4" y="3" width="16" height="18" rx="1" /><path d="M9 21v-5h6v5M8 8h2m4 0h2M8 12h2m4 0h2" /></>,
    alerts: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 9h18c0-1-3-2-3-9ZM10 21h4" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.2 3h-4.4l-.4 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.7h4.4l.4-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5A7 7 0 0 0 19 12Z" /></>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export function Navigation() {
  const path = usePathname();
  return (
    <nav aria-label="Main navigation">
      {links.map(({ href, label, icon }) => {
        const active = href === "/" ? path === href : path === href || path.startsWith(`${href}/`);
        return <Link key={href} href={href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}><NavIcon name={icon} />{label}</Link>;
      })}
    </nav>
  );
}
