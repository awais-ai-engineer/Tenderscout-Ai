import Link from "next/link";

import { SaveButton } from "@/components/save-button";
import { Badge, Empty, ErrorState, NextPage } from "@/components/ui";
import { api, query } from "@/lib/api";
import { positive, source as sourceLabel } from "@/lib/format";

export const dynamic = "force-dynamic";

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

function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 6h16M7 12h10M10 18h4"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
    </svg>
  );
}

function TenderIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 3.75h7l4 4V20H7V3.75Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M14 3.75V8h4M10 12h5M10 15.5h5"
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

function formatDate(value: string | null) {
  if (!value) return "Not provided";

  const parsed = new Date(value);

  if (Number.isNaN(parsed.getTime())) {
    return "Not provided";
  }

  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default async function DiscoverPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;

  const text = (name: string) =>
    typeof params[name] === "string" ? params[name] : "";

  const filters = {
    q: text("q"),
    source: text("source"),
    organization: text("organization"),
    category: text("category"),
    deadline_before: text("deadline_before")
      ? `${text("deadline_before")}T23:59:59Z`
      : undefined,
    cursor: positive(params.cursor),
  };

  let data: Awaited<ReturnType<typeof api.discover>> | undefined;
  let error: unknown;

  let companies: Awaited<ReturnType<typeof api.companies>> = {
    items: [],
    next_cursor: null,
  };

  let saved: Awaited<ReturnType<typeof api.saved>> | null = null;

  try {
    [data, companies] = await Promise.all([
      api.discover(filters),
      api.companies(),
    ]);
  } catch (err) {
    error = err;
  }

  const selectedCompany =
    companies.items.find(
      (item) => item.id === Number(text("company_id")),
    ) || companies.items[0];

  if (selectedCompany) {
    saved = await api.saved(selectedCompany.id).catch(() => null);
  }

  const savedIds = new Set(
    saved?.items.map((item) => item.tender.id) ?? [],
  );

  const hasFilters =
    Boolean(text("q")) ||
    Boolean(text("source")) ||
    Boolean(text("organization")) ||
    Boolean(text("category")) ||
    Boolean(text("deadline_before"));

  return (
    <div className="premium-discover-page">
      <header className="premium-discover-heading">
        <div>
          <span>OPPORTUNITY DISCOVERY</span>

          <h1>Discover Tenders</h1>

          <p>
            Search supported procurement sources and review opportunities from
            one intelligent workspace.
          </p>
        </div>
      </header>

      <section className="discover-search-shell">
        <form className="premium-discover-form" action="/discover">
          <div className="discover-search-row">
            <div className="discover-search-input">
              <SearchIcon />

              <input
                id="search"
                name="q"
                defaultValue={text("q")}
                placeholder="Search tenders, authorities, categories or keywords..."
                minLength={3}
                maxLength={255}
                aria-label="Search procurement opportunities"
              />
            </div>

            <button className="discover-search-button" type="submit">
              <SearchIcon />
              Search
            </button>
          </div>

          <div className="discover-filter-heading">
            <div>
              <FilterIcon />
              <span>Advanced filters</span>
            </div>

            {hasFilters && <Link href="/discover">Clear all</Link>}
          </div>

          <div className="discover-filter-grid">
            <div className="field">
              <label htmlFor="source">Source</label>

              <select
                id="source"
                name="source"
                defaultValue={text("source")}
              >
                <option value="">All sources</option>
                <option value="contracts-finder">Contracts Finder</option>
                <option value="find-a-tender">Find a Tender</option>
                <option value="ted">TED</option>
                <option value="world-bank">World Bank</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="organization">Authority / organisation</label>

              <input
                id="organization"
                name="organization"
                defaultValue={text("organization")}
                placeholder="Any organisation"
                maxLength={255}
              />
            </div>

            <div className="field">
              <label htmlFor="category">Category</label>

              <input
                id="category"
                name="category"
                defaultValue={text("category")}
                placeholder="Any category"
                maxLength={255}
              />
            </div>

            <div className="field">
              <label htmlFor="deadline">Deadline before</label>

              <input
                id="deadline"
                type="date"
                name="deadline_before"
                defaultValue={text("deadline_before")}
              />
            </div>

            <div className="field">
              <label htmlFor="company_id">Company profile</label>

              <select
                id="company_id"
                name="company_id"
                defaultValue={selectedCompany?.id}
              >
                <option value="">No company selected</option>

                {companies.items.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </form>
      </section>

      {error ? (
        <ErrorState error={error} />
      ) : (
        data && (
          <>
            <section className="discover-results-toolbar">
              <div>
                <strong>{data.result_count.toLocaleString()}</strong>

                <span>
                  {data.result_count === 1
                    ? " opportunity shown"
                    : " opportunities shown"}
                </span>
              </div>

              <div className="discover-mode">
                <span
                  className={
                    data.mode === "live" ? "live-dot" : "recorded-dot"
                  }
                />

                {data.mode === "live"
                  ? "Live source search"
                  : "Recorded opportunities"}
              </div>
            </section>

            {data.sources.length > 0 && (
              <section
                className="discover-source-status"
                aria-label="Procurement source status"
              >
                {data.sources.map((item) => (
                  <div
                    key={item.source}
                    className={`discover-source-pill ${
                      item.status === "success" ? "success" : "warning"
                    }`}
                  >
                    <span className="source-status-dot" />

                    <strong>{sourceLabel(item.source)}</strong>

                    <span>
                      {item.status === "success"
                        ? "Live"
                        : "Recorded fallback"}
                    </span>
                  </div>
                ))}
              </section>
            )}

            {selectedCompany && (
              <section className="discover-company-context">
                <span>Company context</span>

                <strong>{selectedCompany.name}</strong>

                <span>
                  Save relevant opportunities to this company profile.
                </span>
              </section>
            )}

            {data.items.length ? (
              <section className="discover-results-list">
                {data.items.map((tender) => (
                  <article className="discover-tender-card" key={tender.id}>
                    <div
                      className={`discover-source-icon ${sourceClass(
                        tender.source,
                      )}`}
                    >
                      <TenderIcon />
                    </div>

                    <div className="discover-tender-content">
                      <div className="discover-tender-topline">
                        <span
                          className={`discover-source-label ${sourceClass(
                            tender.source,
                          )}`}
                        >
                          {sourceLabel(tender.source)}
                        </span>

                        {tender.freshly_fetched ? (
                          <span className="fresh-result-badge">
                            Fresh result
                          </span>
                        ) : (
                          <span className="recorded-result-badge">
                            Recorded
                          </span>
                        )}

                        {tender.category && (
                          <span className="discover-category-badge">
                            {tender.category}
                          </span>
                        )}
                      </div>

                      <Link
                        href={`/tenders/${tender.id}`}
                        className="discover-tender-title"
                      >
                        {tender.title}
                      </Link>

                      <p className="discover-tender-authority">
                        {tender.organization || "Authority not provided"}
                      </p>

                      <div className="discover-tender-meta">
                        <span>
                          <strong>Location</strong>
                          {tender.location || "Not provided"}
                        </span>

                        <span>
                          <strong>Deadline</strong>
                          {formatDate(tender.deadline)}
                        </span>

                        <span>
                          <strong>Published</strong>
                          {formatDate(tender.published_at)}
                        </span>

                        <span>
                          <strong>Analysis</strong>

                          {tender.latest_analysis_status ? (
                            <Badge value={tender.latest_analysis_status} />
                          ) : (
                            "Not analyzed"
                          )}
                        </span>
                      </div>
                    </div>

                    <div className="discover-tender-actions">
                      {selectedCompany && (
                        <SaveButton
                          companyId={selectedCompany.id}
                          tenderId={tender.id}
                          initial={savedIds.has(tender.id)}
                        />
                      )}

                      <Link
                        className="button secondary discover-details-button"
                        href={`/tenders/${tender.id}`}
                      >
                        View details
                        <ArrowIcon />
                      </Link>
                    </div>
                  </article>
                ))}
              </section>
            ) : (
              <section className="discover-empty-shell">
                <Empty title="No opportunities found">
                  Try a different keyword or adjust your filters.
                </Empty>
              </section>
            )}

            <NextPage
              href={
                data.next_cursor
                  ? `/discover${query({
                      q: text("q"),
                      source: text("source"),
                      organization: text("organization"),
                      category: text("category"),
                      deadline_before: text("deadline_before"),
                      company_id: selectedCompany?.id,
                      cursor: data.next_cursor,
                    })}`
                  : null
              }
            />
          </>
        )
      )}
    </div>
  );
}