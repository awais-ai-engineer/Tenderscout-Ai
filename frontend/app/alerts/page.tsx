import Link from "next/link";

import { Empty, ErrorState, NextPage } from "@/components/ui";
import { ReadAlertButton } from "@/components/read-alert-button";
import { api, query } from "@/lib/api";
import { date, label, positive } from "@/lib/format";

export const dynamic = "force-dynamic";

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

function MatchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 3.5 14.5 9l5.5.8-4 3.9.9 5.5L12 16.6 7.1 19.2l.9-5.5-4-3.9L9.5 9 12 3.5Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function UpdateIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M19 8V4m0 0h-4m4 0-3.2 3.2A7 7 0 1 0 19 13"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="8"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M12 8v4l3 2"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CompanyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M5 20V7l7-3 7 3v13H5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M9 10h1M14 10h1M9 14h1M14 14h1M10 20v-3h4v3"
        stroke="currentColor"
        strokeWidth="1.6"
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

function alertTone(type: string) {
  switch (type) {
    case "new_match":
      return "match";
    case "tender_updated":
      return "update";
    case "deadline_reminder":
      return "deadline";
    default:
      return "default";
  }
}

function AlertTypeIcon({ type }: { type: string }) {
  if (type === "new_match") return <MatchIcon />;
  if (type === "tender_updated") return <UpdateIcon />;
  if (type === "deadline_reminder") return <ClockIcon />;

  return <BellIcon />;
}

export default async function AlertsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;

  let companies: Awaited<ReturnType<typeof api.companies>>;

  try {
    companies = await api.companies();
  } catch (error) {
    return (
      <div className="premium-alerts-page">
        <ErrorState error={error} />
      </div>
    );
  }

  const company =
    companies.items.find(
      (item) => item.id === Number(search.company_id),
    ) || companies.items[0];

  const unreadOnly = search.unread === "1";

  let data: Awaited<ReturnType<typeof api.alerts>> | null = null;
  let error: unknown;

  if (company) {
    try {
      data = await api.alerts(
        company.id,
        unreadOnly,
        positive(search.cursor),
      );
    } catch (err) {
      error = err;
    }
  }

  const unreadCount =
    data?.items.filter((item) => !item.read_at).length ?? 0;

  const matchCount =
    data?.items.filter((item) => item.type === "new_match").length ?? 0;

  const updateCount =
    data?.items.filter((item) => item.type === "tender_updated").length ?? 0;

  const deadlineCount =
    data?.items.filter(
      (item) => item.type === "deadline_reminder",
    ).length ?? 0;

  return (
    <div className="premium-alerts-page">
      <header className="premium-alerts-heading">
        <div>
          <span>PROCUREMENT MONITORING</span>

          <h1>Alerts</h1>

          <p>
            Track matching signals, tender changes and approaching deadlines
            from one attention feed.
          </p>
        </div>

        {company && (
          <Link
            href={`/companies/${company.id}`}
            className="alerts-company-context"
          >
            <CompanyIcon />

            <span>
              <small>ACTIVE PROFILE</small>
              <strong>{company.name}</strong>
            </span>

            <ArrowIcon />
          </Link>
        )}
      </header>

      {companies.items.length > 1 && (
        <form className="alerts-filter-panel" action="/alerts">
          <div className="alerts-filter-field">
            <label htmlFor="company">Company profile</label>

            <select
              id="company"
              name="company_id"
              defaultValue={company?.id}
            >
              {companies.items.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>

          <label className="alerts-unread-toggle">
            <input
              type="checkbox"
              name="unread"
              value="1"
              defaultChecked={unreadOnly}
            />

            <span className="alerts-toggle-control" />

            <span>
              <strong>Unread only</strong>
              <small>Hide alerts already reviewed</small>
            </span>
          </label>

          <button type="submit" disabled={!company}>
            Apply filters
          </button>
        </form>
      )}

      {!company ? (
        <section className="alerts-empty-shell">
          <Empty title="Create a company profile first">
            Alerts are generated in the context of a company profile.
          </Empty>

          <Link href="/companies/new" className="button">
            Create company profile
          </Link>
        </section>
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <>
          <section className="alerts-summary-grid">
            <article className="alerts-summary-card violet">
              <span className="alerts-summary-icon">
                <BellIcon />
              </span>

              <div>
                <span>Unread alerts</span>
                <strong>{unreadCount}</strong>
                <small>Needs your attention</small>
              </div>
            </article>

            <article className="alerts-summary-card green">
              <span className="alerts-summary-icon">
                <MatchIcon />
              </span>

              <div>
                <span>New matches</span>
                <strong>{matchCount}</strong>
                <small>Company-fit signals shown</small>
              </div>
            </article>

            <article className="alerts-summary-card blue">
              <span className="alerts-summary-icon">
                <UpdateIcon />
              </span>

              <div>
                <span>Tender updates</span>
                <strong>{updateCount}</strong>
                <small>Tracked opportunities changed</small>
              </div>
            </article>

            <article className="alerts-summary-card amber">
              <span className="alerts-summary-icon">
                <ClockIcon />
              </span>

              <div>
                <span>Deadline reminders</span>
                <strong>{deadlineCount}</strong>
                <small>Closing-date attention signals</small>
              </div>
            </article>
          </section>

          <section className="alerts-feed-shell">
            <header className="alerts-feed-header">
              <div>
                <span>ATTENTION FEED</span>

                <h2>
                  {unreadOnly ? "Unread alerts" : "Recent alerts"}
                </h2>

                <p>
                  Review important procurement events while keeping each alert
                  connected to the underlying tender.
                </p>
              </div>

              <div className="alerts-feed-filter">
                <Link
                  href={`/alerts${query({
                    company_id: company.id,
                  })}`}
                  className={!unreadOnly ? "active" : ""}
                >
                  All
                </Link>

                <Link
                  href={`/alerts${query({
                    company_id: company.id,
                    unread: 1,
                  })}`}
                  className={unreadOnly ? "active" : ""}
                >
                  Unread
                </Link>
              </div>
            </header>

            {data?.items.length ? (
              <div className="alerts-feed-list">
                {data.items.map((alert) => (
                  <article
                    key={alert.id}
                    className={`premium-alert-card ${
                      alert.read_at ? "read" : "unread"
                    }`}
                  >
                    <span
                      className={`alert-type-icon ${alertTone(
                        alert.type,
                      )}`}
                    >
                      <AlertTypeIcon type={alert.type} />
                    </span>

                    <div className="premium-alert-content">
                      <div className="premium-alert-topline">
                        <span
                          className={`alert-type-badge ${alertTone(
                            alert.type,
                          )}`}
                        >
                          {label(alert.type)}
                        </span>

                        {!alert.read_at && (
                          <span className="alert-unread-badge">
                            New
                          </span>
                        )}

                        <time>{date(alert.created_at, true)}</time>
                      </div>

                      <Link
                        href={`/tenders/${alert.tender_id}`}
                        className="premium-alert-title"
                      >
                        {alert.title}
                      </Link>

                      <p className="premium-alert-tender">
                        {alert.tender_title}
                      </p>

                      <p className="premium-alert-message">
                        {alert.message}
                      </p>

                      <div className="premium-alert-meta">
                        <span>
                          <CompanyIcon />
                          {alert.company_name}
                        </span>

                        <Link href={`/tenders/${alert.tender_id}`}>
                          Open tender
                          <ArrowIcon />
                        </Link>
                      </div>
                    </div>

                    <div className="premium-alert-action">
                      {alert.read_at ? (
                        <span className="alert-read-status">
                          Reviewed
                        </span>
                      ) : (
                        <ReadAlertButton
                          companyId={alert.company_id}
                          alertId={alert.id}
                        />
                      )}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="alerts-empty-results">
                <Empty
                  title={
                    unreadOnly ? "No unread alerts" : "No alerts yet"
                  }
                >
                  Qualifying matches, tender changes and deadline reminders will
                  appear here.
                </Empty>
              </div>
            )}
          </section>

          <NextPage
            href={
              data?.next_cursor
                ? `/alerts${query({
                    company_id: company.id,
                    unread: unreadOnly ? 1 : undefined,
                    cursor: data.next_cursor,
                  })}`
                : null
            }
          />
        </>
      )}
    </div>
  );
}