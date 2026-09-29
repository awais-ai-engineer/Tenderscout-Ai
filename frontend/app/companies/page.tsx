import Link from "next/link";

import { Empty, ErrorState, NextPage } from "@/components/ui";
import { api } from "@/lib/api";
import { positive } from "@/lib/format";

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
      <rect
        x="4"
        y="4"
        width="16"
        height="16"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M8 8h8M8 12h8M8 16h5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
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

function PlusIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path
        d="M10 4v12M4 10h12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
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

export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;

  let data: Awaited<ReturnType<typeof api.companies>> | undefined;
  let error: unknown;

  try {
    data = await api.companies(positive(params.cursor));
  } catch (err) {
    error = err;
  }

  const profiles = data?.items ?? [];
  const primary = profiles[0];

  const completenessCount = primary
    ? [
        primary.capabilities_complete,
        primary.certifications_complete,
        primary.experience_complete,
        primary.financials_complete,
      ].filter(Boolean).length
    : 0;

  const completenessPercent =
    primary ? Math.round((completenessCount / 4) * 100) : 0;

  if (error) {
    return (
      <div className="company-hub-page">
        <ErrorState error={error} />
      </div>
    );
  }

  return (
    <div className="company-hub-page">
      <header className="company-hub-heading">
        <div>
          <span>COMPANY INTELLIGENCE</span>

          <h1>Company Profile</h1>

          <p>
            Build the company evidence TenderScout uses for explainable
            procurement matching and opportunity discovery.
          </p>
        </div>

        {profiles.length > 1 && (
          <Link
            href="/companies/new"
            className="button company-hub-add"
          >
            <PlusIcon />
            Add company
          </Link>
        )}
      </header>

      {!primary ? (
        <section className="company-hub-onboarding">
          <div className="company-hub-onboarding-icon">
            <CompanyIcon />
          </div>

          <span>START MATCHING SMARTER</span>

          <h2>Build your company profile</h2>

          <p>
            Add your capabilities, certifications, experience and financial
            information so TenderScout can compare real company evidence with
            tender requirements.
          </p>

          <Link href="/companies/new" className="button">
            <PlusIcon />
            Create company profile
          </Link>
        </section>
      ) : profiles.length === 1 ? (
        <>
          <section className="company-hub-hero">
            <div className="company-hub-company">
              <span className="company-hub-avatar">
                <CompanyIcon />
              </span>

              <div>
                <span className="company-hub-kicker">
                  ACTIVE COMPANY PROFILE
                </span>

                <h2>{primary.name}</h2>

                <p>
                  {primary.country || "Country not provided"} · Company-provided
                  procurement profile
                </p>

                <div className="company-hub-badges">
                  <span>
                    <CheckIcon />
                    Matching enabled
                  </span>

                  <span>
                    {completenessPercent}% profile completeness
                  </span>
                </div>
              </div>
            </div>

            <div className="company-hub-actions">
              <Link
                href={`/discover?company_id=${primary.id}`}
                className="button secondary"
              >
                Find opportunities
                <ArrowIcon />
              </Link>

              <Link
                href={`/companies/${primary.id}`}
                className="button"
              >
                View full profile
                <ArrowIcon />
              </Link>
            </div>
          </section>

          <section className="company-hub-stats">
            <article>
              <span className="company-hub-stat-icon violet">
                <CapabilityIcon />
              </span>

              <div>
                <span>Capabilities</span>
                <strong>{primary.capability_count}</strong>
                <small>Products and delivery strengths</small>
              </div>
            </article>

            <article>
              <span className="company-hub-stat-icon blue">
                <CertificationIcon />
              </span>

              <div>
                <span>Certifications</span>
                <strong>{primary.certification_count}</strong>
                <small>Credentials recorded</small>
              </div>
            </article>

            <article>
              <span className="company-hub-stat-icon green">
                <ExperienceIcon />
              </span>

              <div>
                <span>Experience</span>
                <strong>{primary.experience_count}</strong>
                <small>Project records supplied</small>
              </div>
            </article>

            <article>
              <div
                className="company-hub-completeness-ring"
                style={{
                  background: `conic-gradient(#6751d6 ${completenessPercent}%, #ebe9f4 ${completenessPercent}% 100%)`,
                }}
              >
                <span>
                  <strong>{completenessPercent}%</strong>
                  <small>Complete</small>
                </span>
              </div>
            </article>
          </section>

          <section className="company-hub-content">
            <article className="company-hub-intelligence">
              <header>
                <span>HOW TENDERSCOUT USES YOUR PROFILE</span>

                <h2>Company evidence becomes matching intelligence</h2>

                <p>
                  TenderScout compares recorded company facts against tender
                  requirements while keeping missing information unknown instead
                  of guessing.
                </p>
              </header>

              <div className="company-hub-process">
                <div>
                  <span>01</span>

                  <strong>Company evidence</strong>

                  <p>
                    Capabilities, certifications, experience and financial facts.
                  </p>
                </div>

                <div className="company-hub-process-arrow">
                  <ArrowIcon />
                </div>

                <div>
                  <span>02</span>

                  <strong>Tender requirements</strong>

                  <p>
                    Eligibility, technical, commercial and submission criteria.
                  </p>
                </div>

                <div className="company-hub-process-arrow">
                  <ArrowIcon />
                </div>

                <div>
                  <span>03</span>

                  <strong>Explainable match</strong>

                  <p>
                    Confirmed alignment, unknowns and evidence that needs review.
                  </p>
                </div>
              </div>
            </article>

            <aside className="company-hub-status">
              <header>
                <span>PROFILE STATUS</span>
                <h2>Completeness</h2>
              </header>

              <div className="company-hub-status-list">
                {[
                  {
                    label: "Capabilities",
                    value: primary.capabilities_complete,
                  },
                  {
                    label: "Certifications",
                    value: primary.certifications_complete,
                  },
                  {
                    label: "Experience",
                    value: primary.experience_complete,
                  },
                  {
                    label: "Financials",
                    value: primary.financials_complete,
                  },
                ].map((item) => (
                  <div key={item.label}>
                    <span
                      className={
                        item.value
                          ? "company-status-complete"
                          : "company-status-incomplete"
                      }
                    >
                      {item.value && <CheckIcon />}
                    </span>

                    <strong>{item.label}</strong>

                    <small>
                      {item.value
                        ? "Asserted complete"
                        : "More information may help"}
                    </small>
                  </div>
                ))}
              </div>

              <Link
                href={`/companies/${primary.id}`}
                className="company-hub-status-link"
              >
                Review profile details
                <ArrowIcon />
              </Link>
            </aside>
          </section>
        </>
      ) : (
        <section className="company-hub-multi">
          <header>
            <div>
              <span>COMPANY WORKSPACE</span>
              <h2>Your company profiles</h2>
              <p>
                Choose the company context used for procurement matching.
              </p>
            </div>

            <Link href="/companies/new" className="button">
              <PlusIcon />
              Add company
            </Link>
          </header>

          <div className="company-hub-profile-grid">
            {profiles.map((company) => {
              const complete = [
                company.capabilities_complete,
                company.certifications_complete,
                company.experience_complete,
                company.financials_complete,
              ].filter(Boolean).length;

              const percent = Math.round((complete / 4) * 100);

              return (
                <article
                  className="company-hub-profile-card"
                  key={company.id}
                >
                  <div className="company-hub-profile-card-top">
                    <span>
                      <CompanyIcon />
                    </span>

                    <div>
                      <strong>{company.name}</strong>
                      <small>
                        {company.country || "Country not provided"}
                      </small>
                    </div>
                  </div>

                  <div className="company-hub-profile-card-counts">
                    <span>
                      <strong>{company.capability_count}</strong>
                      Capabilities
                    </span>

                    <span>
                      <strong>{company.certification_count}</strong>
                      Certifications
                    </span>

                    <span>
                      <strong>{company.experience_count}</strong>
                      Experience
                    </span>
                  </div>

                  <div className="company-hub-profile-progress">
                    <div>
                      <span style={{ width: `${percent}%` }} />
                    </div>

                    <strong>{percent}% complete</strong>
                  </div>

                  <Link href={`/companies/${company.id}`}>
                    Open profile
                    <ArrowIcon />
                  </Link>
                </article>
              );
            })}
          </div>
        </section>
      )}

      <NextPage
        href={
          data?.next_cursor
            ? `/companies?cursor=${data.next_cursor}`
            : null
        }
      />
    </div>
  );
}