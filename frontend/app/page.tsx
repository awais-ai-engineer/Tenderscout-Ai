import Link from "next/link";

import { ErrorState } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

function TenderIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 3.5h7l4 4V20H7V3.5Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path
        d="M14 3.5V8h4M10 12h5M10 15.5h5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MatchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="12"
        cy="8"
        r="3"
        stroke="currentColor"
        strokeWidth="1.7"
      />
      <path
        d="M6.5 19c.6-3.6 2.5-5.5 5.5-5.5s4.9 1.9 5.5 5.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 4h10v16l-5-3-5 3V4Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
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
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path
        d="M10 18a2.2 2.2 0 0 0 4 0"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M4 10h11M11 6l4 4-4 4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3Z"
        fill="currentColor"
      />
      <path
        d="m18.5 15 1 2.5L22 18.5l-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z"
        fill="currentColor"
        opacity="0.65"
      />
    </svg>
  );
}

function formatDate(value: string | null) {
  if (!value) return "No deadline";

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return "No deadline";
  }

  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

export default async function DashboardPage() {
  let data: Awaited<ReturnType<typeof api.dashboard>>;

  let companies: Awaited<ReturnType<typeof api.companies>> = {
    items: [],
    next_cursor: null,
  };

  try {
    [data, companies] = await Promise.all([
      api.dashboard(),
      api.companies(),
    ]);
  } catch (error) {
    return <ErrorState error={error} />;
  }

  const company = companies.items[0];

  const title = company
    ? `Welcome back, ${company.name}`
    : "Hi, welcome to TenderScout AI";

  const activeShare =
    data.tender_count > 0
      ? Math.round(
          (data.active_tenders_count / data.tender_count) * 100,
        )
      : 0;

  const matchShare =
    data.tender_count > 0
      ? Math.min(
          100,
          Math.round(
            (data.matching_opportunities_count /
              data.tender_count) *
              100,
          ),
        )
      : 0;

  const savedShare =
    data.tender_count > 0
      ? Math.min(
          100,
          Math.round(
            (data.saved_tenders_count / data.tender_count) * 100,
          ),
        )
      : 0;

  const deadlineGroups = new Map<string, number>();

  for (const tender of data.upcoming_deadlines) {
    const key = formatDate(tender.deadline);

    deadlineGroups.set(
      key,
      (deadlineGroups.get(key) || 0) + 1,
    );
  }

  const deadlineRows = Array.from(deadlineGroups.entries()).slice(0, 6);

  const maxDeadlineCount = Math.max(
    ...deadlineRows.map(([, count]) => count),
    1,
  );

  const categoryGroups = new Map<string, number>();

  for (const tender of data.upcoming_deadlines) {
    const category =
      tender.category?.trim() || "Other";

    categoryGroups.set(
      category,
      (categoryGroups.get(category) || 0) + 1,
    );
  }

  const categoryRows = Array.from(categoryGroups.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  const categoryTotal = Math.max(
    categoryRows.reduce(
      (total, [, count]) => total + count,
      0,
    ),
    1,
  );

  return (
    <div className="executive-overview">
      <section className="executive-welcome">
        <div className="executive-welcome-copy">
          <div className="executive-live-chip">
            <span className="executive-live-dot" />
            Procurement intelligence
          </div>

          <h1>{title}</h1>

          <p>
            {company
              ? "Monitor opportunities, matching activity and procurement signals from one workspace."
              : "Create your company profile and start discovering procurement opportunities."}
          </p>
        </div>

        <div className="executive-welcome-art">
          <span className="executive-orbit orbit-one" />
          <span className="executive-orbit orbit-two" />

          <div className="executive-intelligence-badge">
            <span>
              <SparkIcon />
            </span>

            <div>
              <small>TENDERSCOUT AI</small>
              <strong>Opportunity intelligence</strong>
            </div>
          </div>
        </div>
      </section>

      <section className="executive-metrics">
        <article className="executive-metric violet">
          <div className="executive-metric-top">
            <span className="executive-metric-icon">
              <TenderIcon />
            </span>

            <span className="executive-metric-label">
              Active tenders
            </span>
          </div>

          <div className="executive-metric-value">
            {data.active_tenders_count.toLocaleString()}
          </div>

          <div className="executive-metric-bottom">
            <div className="executive-progress">
              <span style={{ width: `${activeShare}%` }} />
            </div>

            <span>{activeShare}% of recorded</span>
          </div>
        </article>

        <article className="executive-metric emerald">
          <div className="executive-metric-top">
            <span className="executive-metric-icon">
              <MatchIcon />
            </span>

            <span className="executive-metric-label">
              Matching opportunities
            </span>
          </div>

          <div className="executive-metric-value">
            {data.matching_opportunities_count.toLocaleString()}
          </div>

          <div className="executive-metric-bottom">
            <div className="executive-progress">
              <span style={{ width: `${matchShare}%` }} />
            </div>

            <span>{matchShare}% profile coverage</span>
          </div>
        </article>

        <article className="executive-metric blue">
          <div className="executive-metric-top">
            <span className="executive-metric-icon">
              <BookmarkIcon />
            </span>

            <span className="executive-metric-label">
              Saved tenders
            </span>
          </div>

          <div className="executive-metric-value">
            {data.saved_tenders_count.toLocaleString()}
          </div>

          <div className="executive-metric-bottom">
            <div className="executive-progress">
              <span style={{ width: `${savedShare}%` }} />
            </div>

            <Link href="/saved">
              Open shortlist
              <ArrowIcon />
            </Link>
          </div>
        </article>

        <article className="executive-metric rose">
          <div className="executive-metric-top">
            <span className="executive-metric-icon">
              <BellIcon />
            </span>

            <span className="executive-metric-label">
              Unread alerts
            </span>
          </div>

          <div className="executive-metric-value">
            {data.unread_alerts_count.toLocaleString()}
          </div>

          <div className="executive-metric-bottom">
            <span className="executive-alert-status">
              <span />
              Attention feed
            </span>

            <Link href="/alerts">
              Review
              <ArrowIcon />
            </Link>
          </div>
        </article>
      </section>

      <section className="executive-intelligence-grid">
        <article className="executive-panel deadline-radar">
          <header>
            <div>
              <span className="executive-panel-kicker">
                OPPORTUNITY TIMING
              </span>

              <h2>Deadline radar</h2>

              <p>
                Upcoming tender concentration by closing date.
              </p>
            </div>

            <Link href="/discover">
              Explore tenders
              <ArrowIcon />
            </Link>
          </header>

          <div className="deadline-radar-body">
            {deadlineRows.length ? (
              deadlineRows.map(([label, count]) => {
                const width = Math.max(
                  12,
                  Math.round(
                    (count / maxDeadlineCount) * 100,
                  ),
                );

                return (
                  <div
                    className="deadline-radar-row"
                    key={label}
                  >
                    <span>{label}</span>

                    <div className="deadline-radar-track">
                      <span
                        style={{ width: `${width}%` }}
                      />
                    </div>

                    <strong>{count}</strong>
                  </div>
                );
              })
            ) : (
              <div className="executive-empty">
                No upcoming deadlines available.
              </div>
            )}
          </div>

          <footer>
            <span>
              {data.active_tenders_count.toLocaleString()} active
              opportunities
            </span>

            <span>
              {data.upcoming_deadlines.length.toLocaleString()} shown
              in deadline radar
            </span>
          </footer>
        </article>

        <article className="executive-panel category-intelligence">
          <header>
            <div>
              <span className="executive-panel-kicker">
                PORTFOLIO INTELLIGENCE
              </span>

              <h2>Top categories</h2>

              <p>
                Current category concentration in upcoming tenders.
              </p>
            </div>
          </header>

          <div className="category-intelligence-body">
            {categoryRows.length ? (
              categoryRows.map(
                ([category, count], index) => {
                  const share = Math.round(
                    (count / categoryTotal) * 100,
                  );

                  return (
                    <div
                      className="category-intelligence-row"
                      key={category}
                    >
                      <div className="category-intelligence-name">
                        <span>{index + 1}</span>

                        <strong>{category}</strong>
                      </div>

                      <div className="category-intelligence-meta">
                        <span>{count} tenders</span>
                        <strong>{share}%</strong>
                      </div>

                      <div className="category-intelligence-track">
                        <span
                          style={{ width: `${share}%` }}
                        />
                      </div>
                    </div>
                  );
                },
              )
            ) : (
              <div className="executive-empty">
                No category data available yet.
              </div>
            )}
          </div>

          <div className="category-intelligence-summary">
            <div>
              <span>Recorded tenders</span>
              <strong>
                {data.tender_count.toLocaleString()}
              </strong>
            </div>

            <div>
              <span>Company profiles</span>
              <strong>
                {data.company_count.toLocaleString()}
              </strong>
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}