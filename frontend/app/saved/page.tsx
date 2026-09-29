import Link from "next/link";

import { SaveButton } from "@/components/save-button";
import { Empty, ErrorState, NextPage } from "@/components/ui";
import { api, query } from "@/lib/api";
import { date, positive, source } from "@/lib/format";

export const dynamic = "force-dynamic";

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

function TenderIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 3.5h7l4 4V20H7V3.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M14 3.5V8h4M10 12h5M10 15.5h5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
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

function sourceClass(value: string) {
  switch (value) {
    case "contracts-finder":
      return "contracts";
    case "find-a-tender":
      return "fts";
    case "ted":
      return "ted";
    case "world-bank":
      return "world-bank";
    default:
      return "default";
  }
}

export default async function SavedPage({
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
      <div className="premium-saved-page">
        <header className="premium-saved-heading">
          <span>YOUR SHORTLIST</span>
          <h1>Saved Tenders</h1>
          <p>
            Keep important opportunities organised and return to them quickly.
          </p>
        </header>

        <ErrorState error={error} />
      </div>
    );
  }

  const requested = Number(
    typeof search.company_id === "string" ? search.company_id : 0,
  );

  const company =
    companies.items.find((item) => item.id === requested) ||
    companies.items[0];

  let data: Awaited<ReturnType<typeof api.saved>> | null = null;
  let error: unknown;

  if (company) {
    try {
      data = await api.saved(company.id, positive(search.cursor));
    } catch (err) {
      error = err;
    }
  }

  const updatedCount =
    data?.items.filter((item) => item.updated_since_saved).length ?? 0;

  const analyzedCount =
    data?.items.filter(
      (item) => item.tender.latest_analysis_status !== null,
    ).length ?? 0;

  return (
    <div className="premium-saved-page">
      <header className="premium-saved-heading">
        <div>
          <span>YOUR SHORTLIST</span>

          <h1>Saved Tenders</h1>

          <p>
            Keep priority procurement opportunities organised, monitor changes,
            and return to source evidence when you are ready to act.
          </p>
        </div>

        {company && (
          <Link
            href={`/companies/${company.id}`}
            className="saved-company-context"
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
        <form className="saved-company-switcher" action="/saved">
          <div>
            <label htmlFor="company">Saved for company</label>

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
            View shortlist
          </button>
        </form>
      )}

      {!company ? (
        <section className="saved-empty-shell">
          <Empty title="Create a company profile first">
            Add company information before building a procurement shortlist.
          </Empty>

          <Link href="/companies/new" className="button">
            Create company profile
          </Link>
        </section>
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <>
          <section className="saved-summary-grid">
            <article className="saved-summary-card violet">
              <span className="saved-summary-icon">
                <BookmarkIcon />
              </span>

              <div>
                <span>Saved opportunities</span>

                <strong>
                  {data?.items.length.toLocaleString() ?? "0"}
                </strong>

                <small>Current shortlist page</small>
              </div>
            </article>

            <article className="saved-summary-card amber">
              <span className="saved-summary-icon">
                <UpdateIcon />
              </span>

              <div>
                <span>Updated since saved</span>

                <strong>{updatedCount.toLocaleString()}</strong>

                <small>May require another review</small>
              </div>
            </article>

            <article className="saved-summary-card blue">
              <span className="saved-summary-icon">
                <TenderIcon />
              </span>

              <div>
                <span>With analysis</span>

                <strong>{analyzedCount.toLocaleString()}</strong>

                <small>Analysis status recorded</small>
              </div>
            </article>
          </section>

          <section className="saved-results-shell">
            <header className="saved-results-header">
              <div>
                <span>PROCUREMENT SHORTLIST</span>

                <h2>Priority opportunities</h2>

                <p>
                  Your saved tenders stay connected to their source, deadlines,
                  analysis status and recorded updates.
                </p>
              </div>

              <Link href="/discover" className="saved-discover-link">
                Discover more
                <ArrowIcon />
              </Link>
            </header>

            {data?.items.length ? (
              <div className="saved-card-grid">
                {data.items.map((item) => (
                  <article className="premium-saved-card" key={item.id}>
                    <div className="saved-card-top">
                      <span
                        className={`saved-source-icon ${sourceClass(
                          item.tender.source,
                        )}`}
                      >
                        <TenderIcon />
                      </span>

                      <div className="saved-card-badges">
                        <span
                          className={`saved-source-badge ${sourceClass(
                            item.tender.source,
                          )}`}
                        >
                          {source(item.tender.source)}
                        </span>

                        {item.updated_since_saved && (
                          <span className="saved-updated-badge">
                            <UpdateIcon />
                            Updated
                          </span>
                        )}
                      </div>
                    </div>

                    <Link
                      href={`/tenders/${item.tender.id}?company_id=${company.id}`}
                      className="saved-card-title"
                    >
                      {item.tender.title}
                    </Link>

                    <p className="saved-card-authority">
                      {item.tender.organization || "Authority not provided"}
                    </p>

                    <div className="saved-card-details">
                      <div>
                        <span>Deadline</span>
                        <strong>{date(item.tender.deadline)}</strong>
                      </div>

                      <div>
                        <span>Category</span>
                        <strong>
                          {item.tender.category || "Not provided"}
                        </strong>
                      </div>

                      <div>
                        <span>Saved</span>
                        <strong>{date(item.saved_at)}</strong>
                      </div>

                      <div>
                        <span>Analysis</span>
                        <strong>
                          {item.tender.latest_analysis_status
                            ? item.tender.latest_analysis_status
                            : "Not analyzed"}
                        </strong>
                      </div>
                    </div>

                    <div className="saved-card-footer">
                      <Link
                        href={`/tenders/${item.tender.id}?company_id=${company.id}`}
                        className="saved-review-link"
                      >
                        Review tender
                        <ArrowIcon />
                      </Link>

                      <SaveButton
                        companyId={company.id}
                        tenderId={item.tender.id}
                        initial
                      />
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="saved-empty-results">
                <Empty title="No saved tenders">
                  Save opportunities from Discover or a tender detail page and
                  they will appear here.
                </Empty>

                <Link href="/discover" className="button">
                  Discover tenders
                </Link>
              </div>
            )}
          </section>

          <NextPage
            href={
              data?.next_cursor
                ? `/saved${query({
                    company_id: company.id,
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