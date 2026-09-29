import Link from "next/link";
import { notFound } from "next/navigation";

import {
  Badge,
  Empty,
  ErrorState,
  NextPage,
  SafeLink,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { date, positive } from "@/lib/format";

export const dynamic = "force-dynamic";

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

function CapabilityIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M8 8h8M8 12h8M8 16h5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <rect
        x="4"
        y="4"
        width="16"
        height="16"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function CertificationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle
        cx="12"
        cy="10"
        r="5"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="m9 14-1 6 4-2 4 2-1-6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ExperienceIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect
        x="4"
        y="7"
        width="16"
        height="12"
        rx="2"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M9 7V5h6v2M4 12h16"
        stroke="currentColor"
        strokeWidth="1.6"
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

function GlobeIcon() {
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
        d="M4 12h16M12 4c2 2.2 3 4.9 3 8s-1 5.8-3 8c-2-2.2-3-4.9-3-8s1-5.8 3-8Z"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="m5 10 3 3 7-7"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
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

function displayMoney(
  amount: string | null,
  currency: string | null,
) {
  if (!amount) return "Not provided";

  return currency ? `${currency} ${amount}` : amount;
}

export default async function CompanyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { id } = await params;
  const search = await searchParams;

  if (!positive(id)) notFound();

  let company: Awaited<ReturnType<typeof api.company>>;
  let matches: Awaited<
    ReturnType<typeof api.matches>
  >;

  try {
    [company, matches] = await Promise.all([
      api.company(id),
      api.matches(
        "companies",
        id,
        positive(search.cursor),
      ),
    ]);
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 404
    ) {
      notFound();
    }

    return <ErrorState error={error} />;
  }

  const {
    capabilities,
    certifications,
    experience,
    ...profile
  } = company.profile;

  const completenessItems = [
    {
      label: "Capabilities",
      complete: profile.capabilities_complete,
    },
    {
      label: "Certifications",
      complete: profile.certifications_complete,
    },
    {
      label: "Experience",
      complete: profile.experience_complete,
    },
    {
      label: "Financials",
      complete: profile.financials_complete,
    },
  ];

  const assertedComplete = completenessItems.filter(
    (item) => item.complete,
  ).length;

  const scoredMatches = matches.items.filter(
    (match) => match.score !== null,
  );

  const averageShownFit =
    scoredMatches.length > 0
      ? Math.round(
          scoredMatches.reduce(
            (total, match) =>
              total + (match.score ?? 0),
            0,
          ) / scoredMatches.length,
        )
      : null;

  return (
    <div className="premium-company-page">
      <Link
        className="company-back-link"
        href="/companies"
      >
        ← Company Profile
      </Link>

      <section className="company-profile-hero">
        <div className="company-profile-identity">
          <span className="company-profile-avatar">
            <CompanyIcon />
          </span>

          <div>
            <span className="company-profile-kicker">
              COMPANY PROFILE
            </span>

            <h1>{profile.name}</h1>

            <p>
              {profile.description ||
                "No company description has been provided yet."}
            </p>

            <div className="company-profile-meta">
              <span>
                <strong>Country</strong>
                {profile.country || "Not provided"}
              </span>

              <span>
                <strong>Years in business</strong>
                {profile.years_in_business ??
                  "Not provided"}
              </span>

              <span>
                <strong>Employees</strong>
                {profile.employee_count ??
                  "Not provided"}
              </span>
            </div>
          </div>
        </div>

        <div className="company-profile-actions">
          {profile.website && (
            <span className="company-website-action">
              <GlobeIcon />

              <SafeLink href={profile.website}>
                Visit website
              </SafeLink>
            </span>
          )}

          <Link
            className="button company-discover-action"
            href={`/discover?company_id=${company.id}`}
          >
            Find opportunities
            <ArrowIcon />
          </Link>
        </div>
      </section>

      <section className="company-profile-stats">
        <article>
          <span className="company-stat-icon violet">
            <CapabilityIcon />
          </span>

          <div>
            <span>Capabilities</span>
            <strong>{capabilities.length}</strong>
            <small>Recorded company capabilities</small>
          </div>
        </article>

        <article>
          <span className="company-stat-icon blue">
            <CertificationIcon />
          </span>

          <div>
            <span>Certifications</span>
            <strong>{certifications.length}</strong>
            <small>Recorded credentials</small>
          </div>
        </article>

        <article>
          <span className="company-stat-icon green">
            <ExperienceIcon />
          </span>

          <div>
            <span>Experience</span>
            <strong>{experience.length}</strong>
            <small>Recorded project history</small>
          </div>
        </article>

        <article>
          <span className="company-stat-icon amber">
            <MatchIcon />
          </span>

          <div>
            <span>Average shown fit</span>

            <strong>
              {averageShownFit === null
                ? "—"
                : `${averageShownFit}%`}
            </strong>

            <small>
              Based on scored matches shown
            </small>
          </div>
        </article>
      </section>

      <section className="company-profile-layout">
        <div className="company-profile-main">
          <section className="company-section">
            <header className="company-section-header">
              <div>
                <span>COMPANY INTELLIGENCE</span>
                <h2>Capabilities</h2>
                <p>
                  Products, services and delivery strengths
                  supplied in this company profile.
                </p>
              </div>

              <span className="company-section-count">
                {capabilities.length}
              </span>
            </header>

            {capabilities.length ? (
              <div className="company-capability-grid">
                {capabilities.map(
                  (capability, index) => (
                    <article
                      className="company-capability-card"
                      key={`${capability.name}-${index}`}
                    >
                      <span>
                        <CapabilityIcon />
                      </span>

                      <div>
                        <strong>
                          {capability.name}
                        </strong>

                        <p>
                          {capability.description ||
                            "No additional description supplied."}
                        </p>
                      </div>
                    </article>
                  ),
                )}
              </div>
            ) : (
              <Empty title="No capabilities recorded">
                This company profile does not contain
                capability records yet.
              </Empty>
            )}
          </section>

          <section className="company-section">
            <header className="company-section-header">
              <div>
                <span>CREDENTIALS</span>
                <h2>Certifications</h2>
                <p>
                  Recorded company certifications and
                  validity information.
                </p>
              </div>

              <span className="company-section-count">
                {certifications.length}
              </span>
            </header>

            {certifications.length ? (
              <div className="company-certification-list">
                {certifications.map(
                  (certification, index) => (
                    <article
                      className="company-certification-card"
                      key={`${certification.name}-${index}`}
                    >
                      <span className="company-certification-icon">
                        <CertificationIcon />
                      </span>

                      <div className="company-certification-content">
                        <strong>
                          {certification.name}
                        </strong>

                        <span>
                          {certification.issuer ||
                            "Issuer not provided"}
                        </span>
                      </div>

                      <div className="company-certification-meta">
                        <span>
                          <small>Identifier</small>
                          {certification.identifier ||
                            "Not provided"}
                        </span>

                        <span>
                          <small>Valid from</small>
                          {date(
                            certification.valid_from,
                          )}
                        </span>

                        <span>
                          <small>Valid until</small>
                          {date(
                            certification.valid_until,
                          )}
                        </span>
                      </div>
                    </article>
                  ),
                )}
              </div>
            ) : (
              <Empty title="No certifications recorded">
                This company profile does not contain
                certification records yet.
              </Empty>
            )}
          </section>

          <section className="company-section">
            <header className="company-section-header">
              <div>
                <span>DELIVERY HISTORY</span>
                <h2>Experience</h2>
                <p>
                  Previous projects and contracts supplied
                  as company evidence.
                </p>
              </div>

              <span className="company-section-count">
                {experience.length}
              </span>
            </header>

            {experience.length ? (
              <div className="company-experience-list">
                {experience.map((item, index) => (
                  <article
                    className="company-experience-card"
                    key={`${item.title}-${index}`}
                  >
                    <div className="company-experience-line">
                      <span />
                    </div>

                    <div className="company-experience-body">
                      <div className="company-experience-heading">
                        <div>
                          <strong>
                            {item.title ||
                              "Untitled experience"}
                          </strong>

                          <span>
                            {item.client ||
                              "Client not provided"}
                          </span>
                        </div>

                        {item.country && (
                          <span className="company-country-badge">
                            {item.country}
                          </span>
                        )}
                      </div>

                      <p>
                        {item.description ||
                          "No description supplied."}
                      </p>

                      <div className="company-experience-meta">
                        <span>
                          <small>Value</small>
                          {displayMoney(
                            item.contract_value,
                            item.currency,
                          )}
                        </span>

                        <span>
                          <small>Started</small>
                          {date(item.started_at)}
                        </span>

                        <span>
                          <small>Completed</small>
                          {date(item.completed_at)}
                        </span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <Empty title="No experience recorded">
                This company profile does not contain
                experience records yet.
              </Empty>
            )}
          </section>

          <section className="company-section">
            <header className="company-section-header">
              <div>
                <span>EXPLAINABLE ALIGNMENT</span>
                <h2>Recorded matches</h2>
                <p>
                  Existing tender comparisons created from
                  this company profile.
                </p>
              </div>

              <span className="company-section-count">
                {matches.items.length}
              </span>
            </header>

            {matches.items.length ? (
              <div className="company-match-list">
                {matches.items.map((match) => (
                  <Link
                    className="company-match-card"
                    href={`/matches/${match.match_id}`}
                    key={match.match_id}
                  >
                    <span className="company-match-icon">
                      <MatchIcon />
                    </span>

                    <div>
                      <strong>
                        Analysis #{match.analysis_id}
                      </strong>

                      <span>
                        Coverage{" "}
                        {Math.round(
                          match.coverage_ratio * 100,
                        )}
                        %
                      </span>
                    </div>

                    <div className="company-match-score">
                      <strong>
                        {match.score === null
                          ? "—"
                          : `${match.score}%`}
                      </strong>

                      <small>Fit</small>
                    </div>

                    <Badge
                      value={
                        match.eligibility_status
                      }
                    />

                    <ArrowIcon />
                  </Link>
                ))}
              </div>
            ) : (
              <Empty title="No recorded matches">
                Open a tender with a completed analysis to
                compare it with this company profile.
              </Empty>
            )}

            <NextPage
              href={
                matches.next_cursor
                  ? `/companies/${id}?cursor=${matches.next_cursor}`
                  : null
              }
            />
          </section>
        </div>

        <aside className="company-profile-side">
          <section className="company-side-card">
            <header>
              <span>PROFILE STATUS</span>
              <h2>Completeness</h2>
            </header>

            <div className="company-completeness-score">
              <strong>
                {assertedComplete}/4
              </strong>

              <span>
                sections asserted complete
              </span>
            </div>

            <div className="company-completeness-list">
              {completenessItems.map((item) => (
                <div key={item.label}>
                  <span
                    className={
                      item.complete
                        ? "complete"
                        : "incomplete"
                    }
                  >
                    {item.complete && <CheckIcon />}
                  </span>

                  <strong>{item.label}</strong>

                  <small>
                    {item.complete
                      ? "Asserted complete"
                      : "Not asserted"}
                  </small>
                </div>
              ))}
            </div>
          </section>

          <section className="company-side-card">
            <header>
              <span>COMPANY FACTS</span>
              <h2>Financial profile</h2>
            </header>

            <div className="company-financial-list">
              <div>
                <span>Annual revenue</span>

                <strong>
                  {displayMoney(
                    profile.annual_revenue,
                    profile.currency,
                  )}
                </strong>
              </div>

              <div>
                <span>Employees</span>

                <strong>
                  {profile.employee_count ??
                    "Not provided"}
                </strong>
              </div>

              <div>
                <span>Years in business</span>

                <strong>
                  {profile.years_in_business ??
                    "Not provided"}
                </strong>
              </div>

              <div>
                <span>Country</span>

                <strong>
                  {profile.country ||
                    "Not provided"}
                </strong>
              </div>
            </div>
          </section>

          <div className="company-profile-note">
            Company facts shown here are supplied by the
            company and are not independently verified by
            TenderScout.
          </div>
        </aside>
      </section>
    </div>
  );
}