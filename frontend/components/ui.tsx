import Link from "next/link";
import type { ReactNode } from "react";
import type { Json, Run, Tender } from "@/lib/types";
import { date, label, source } from "@/lib/format";

export function Heading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow || "Procurement intelligence"}</p>
        <h1>{title}</h1>
        {children && <p className="lede">{children}</p>}
      </div>
      {action}
    </header>
  );
}
export function Badge({ value }: { value: string }) {
  const tone = ["completed", "extracted", "eligible", "added"].includes(value)
    ? "good"
    : ["failed", "ineligible", "removed"].includes(value)
      ? "bad"
      : ["running", "queued", "modified", "partial"].includes(value)
        ? "warm"
        : "neutral";
  return <span className={`badge ${tone}`}>{label(value)}</span>;
}
export function Empty({
  children,
  title = "Nothing here yet",
}: {
  children: ReactNode;
  title?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon" aria-hidden="true">
        ◇
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="notice error" role="alert">
      <strong>Unable to load this view</strong>
      <p>
        {error instanceof Error ? error.message : "Please try again shortly."}
      </p>
      <p>Refresh the page to retry.</p>
    </div>
  );
}
export function Panel({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
export function NextPage({ href }: { href: string | null }) {
  return href ? (
    <div className="pagination">
      <Link className="button secondary" href={href}>
        Next page <span aria-hidden="true">→</span>
      </Link>
    </div>
  ) : null;
}
export function SafeLink({
  href,
  children,
}: {
  href: string | null;
  children: ReactNode;
}) {
  if (!href) return null;
  try {
    const url = new URL(href);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
  } catch {
    return null;
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-link"
    >
      {children} ↗
    </a>
  );
}
export function Facts({ value }: { value: Json }) {
  if (value === null) return <span className="muted">Not provided</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ul className="fact-list">
        {value.map((item, index) => (
          <li key={index}>
            <Facts value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="muted">None recorded</span>
    );
  if (typeof value === "object")
    return (
      <dl className="fact-map">
        {Object.entries(value)
          .filter(([, v]) => v !== null)
          .map(([key, item]) => (
            <div key={key}>
              <dt>{label(key)}</dt>
              <dd>
                <Facts value={item} />
              </dd>
            </div>
          ))}
      </dl>
    );
  return (
    <span>
      {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
    </span>
  );
}
export function TenderTable({
  tenders,
}: {
  tenders: (Tender & { freshly_fetched?: boolean })[];
}) {
  if (!tenders.length)
    return (
      <Empty title="No tenders found">
        Try another search or filter. Recorded opportunities will appear here when available.
      </Empty>
    );
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Tender / authority</th>
            <th>Source</th>
            <th>Category</th>
            <th>Deadline (UTC)</th>
            <th>Analysis</th>
          </tr>
        </thead>
        <tbody>
          {tenders.map((tender) => (
            <tr key={tender.id}>
              <td className="wide">
                <Link className="row-title" href={`/tenders/${tender.id}`}>
                  {tender.title}
                </Link>
                <span className="subtext">
                  {tender.organization || "Authority not provided"}
                </span>
              </td>
              <td>
                {source(tender.source)}
                {tender.freshly_fetched !== undefined && (
                  <span className="subtext">
                    {tender.freshly_fetched ? "Fresh result" : "Recorded result"}
                  </span>
                )}
              </td>
              <td>{tender.category || "Not provided"}</td>
              <td className="nowrap">{date(tender.deadline)}</td>
              <td>
                {tender.latest_analysis_status ? (
                  <Badge value={tender.latest_analysis_status} />
                ) : (
                  <span className="muted">Not analyzed</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function RunTable({ runs }: { runs: Run[] }) {
  if (!runs.length)
    return (
      <Empty title="No pipeline runs">
        Trigger a supported source to begin collecting tender records.
      </Empty>
    );
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Source</th>
            <th>Trigger</th>
            <th>Status</th>
            <th>Started (UTC)</th>
            <th>Stages</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>
                <Link className="text-link" href={`/pipeline/${run.id}`}>
                  #{run.id}
                </Link>
              </td>
              <td>{source(run.source)}</td>
              <td>{label(run.trigger)}</td>
              <td>
                <Badge value={run.status} />
              </td>
              <td>{date(run.started_at || run.created_at, true)}</td>
              <td>{run.stage_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
