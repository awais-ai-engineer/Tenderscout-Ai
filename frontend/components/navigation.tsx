"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
const links = [
  ["/", "Dashboard", "◫"],
  ["/tenders", "Tenders", "▤"],
  ["/companies", "Companies", "▦"],
  ["/pipeline", "Pipeline", "↳"],
];
export function Navigation() {
  const path = usePathname();
  return (
    <nav aria-label="Main navigation">
      {links.map(([href, text, icon]) => {
        const active = href === "/" ? path === href : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={active ? "active" : ""}
            aria-current={active ? "page" : undefined}
          >
            <span aria-hidden="true">{icon}</span>
            {text}
          </Link>
        );
      })}
    </nav>
  );
}
