import Link from "next/link";

import { Empty, ErrorState } from "@/components/ui";
import { NotificationForm } from "@/components/notification-form";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="3"
        stroke="currentColor"
        strokeWidth="1.7"
      />
      <path
        d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"
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

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="4"
        y="6"
        width="16"
        height="12"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="m5 8 7 5 7-5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
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

export default async function SettingsPage({
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
      <div className="premium-settings-page">
        <ErrorState error={error} />
      </div>
    );
  }

  const company =
    companies.items.find(
      (item) => item.id === Number(search.company_id),
    ) || companies.items[0];

  let preferences:
    | Awaited<ReturnType<typeof api.preferences>>
    | null = null;

  let error: unknown;

  if (company) {
    try {
      preferences = await api.preferences(company.id);
    } catch (err) {
      error = err;
    }
  }

  return (
    <div className="premium-settings-page">
      <header className="premium-settings-heading">
        <div>
          <span>WORKSPACE CONTROL</span>

          <h1>Settings</h1>

          <p>
            Configure company-scoped notifications and delivery preferences for
            your TenderScout workspace.
          </p>
        </div>

        {company && (
          <Link
            href={`/companies/${company.id}`}
            className="settings-company-context"
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
        <form className="settings-company-switcher" action="/settings">
          <div>
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

          <button type="submit" disabled={!company}>
            Load settings
          </button>
        </form>
      )}

      {!company ? (
        <section className="settings-empty-shell">
          <Empty title="Create a company profile first">
            Notification preferences are configured for a company profile.
          </Empty>

          <Link href="/companies/new" className="button">
            Create company profile
          </Link>
        </section>
      ) : error ? (
        <ErrorState error={error} />
      ) : preferences ? (
        <>
          <section className="settings-summary-grid">
            <article className="settings-summary-card violet">
              <span className="settings-summary-icon">
                <BellIcon />
              </span>

              <div>
                <span>Alert channels</span>

                <strong>
                  {
                    [
                      preferences.new_match_alerts,
                      preferences.tender_change_alerts,
                      preferences.deadline_reminders,
                    ].filter(Boolean).length
                  }
                  /3
                </strong>

                <small>Alert types enabled</small>
              </div>
            </article>

            <article className="settings-summary-card blue">
              <span className="settings-summary-icon">
                <MailIcon />
              </span>

              <div>
                <span>Email delivery</span>

                <strong>
                  {preferences.email_enabled ? "On" : "Off"}
                </strong>

                <small>
                  {preferences.notification_email ||
                    "No notification email"}
                </small>
              </div>
            </article>

            <article className="settings-summary-card green">
              <span className="settings-summary-icon">
                <SettingsIcon />
              </span>

              <div>
                <span>Minimum fit score</span>

                <strong>
                  {preferences.minimum_match_score}
                </strong>

                <small>Alert threshold</small>
              </div>
            </article>
          </section>

          <section className="settings-layout">
            <aside className="settings-nav-card">
              <span>SETTINGS</span>

              <div className="settings-nav-item active">
                <BellIcon />

                <div>
                  <strong>Notifications</strong>
                  <small>Alerts and delivery</small>
                </div>
              </div>

              <div className="settings-nav-item disabled">
                <CompanyIcon />

                <div>
                  <strong>Workspace</strong>
                  <small>Company-scoped context</small>
                </div>
              </div>

              <div className="settings-nav-note">
                Current settings apply to{" "}
                <strong>{company.name}</strong>.
              </div>
            </aside>

            <section className="settings-main-card">
              <header className="settings-section-header">
                <span>NOTIFICATION PREFERENCES</span>

                <h2>Control what reaches you</h2>

                <p>
                  Choose which procurement events trigger notifications and how
                  they should be delivered.
                </p>
              </header>

              <NotificationForm initial={preferences} />
            </section>
          </section>
        </>
      ) : null}
    </div>
  );
}