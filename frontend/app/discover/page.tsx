import Link from "next/link";
import { api, query } from "@/lib/api";
import { positive, source as sourceLabel } from "@/lib/format";
import {
  ErrorState,
  Heading,
  NextPage,
  Panel,
  TenderTable,
} from "@/components/ui";
export const dynamic = "force-dynamic";
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
  let data, error;
  let companies: Awaited<ReturnType<typeof api.companies>> = {
    items: [],
    next_cursor: null,
  };
  let company;
  let saved: Awaited<ReturnType<typeof api.saved>> | null = null;
  try {
    [data, companies] = await Promise.all([
      api.discover(filters),
      api.companies(),
    ]);
    company =
      companies.items.find((item) => item.id === Number(text("company_id"))) ||
      companies.items[0];
    saved = company ? await api.saved(company.id).catch(() => null) : null;
  } catch (err) {
    error = err;
  }
  return (
    <>
      <Heading eyebrow="Opportunity discovery" title="Discover opportunities">
        Search Contracts Finder, Find a Tender and TED, compare deadlines, and
        review source evidence. A search checks each selected public source;
        browsing without a query uses recorded opportunities.
      </Heading>
      <form className="filters discover-filters" action="/discover">
        <div className="field">
          <label htmlFor="search">Search opportunities</label>
          <input
            id="search"
            name="q"
            defaultValue={text("q")}
            placeholder="Title, authority, category or description…"
            minLength={3}
            maxLength={255}
          />
        </div>
        <div className="field">
          <label htmlFor="company_id">Save for company</label>
          <select id="company_id" name="company_id" defaultValue={company?.id}>
            <option value="">No company selected</option>
            {companies.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="source">Source</label>
          <select id="source" name="source" defaultValue={text("source")}>
            <option value="">All sources</option>
            <option value="contracts-finder">Contracts Finder</option>
            <option value="find-a-tender">Find a Tender</option>
            <option value="ted">TED</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="deadline">Deadline before (UTC)</label>
          <input
            id="deadline"
            type="date"
            name="deadline_before"
            defaultValue={text("deadline_before")}
          />
        </div>
        <button type="submit">Search opportunities</button>
        <Link className="text-link" href="/discover">
          Reset
        </Link>
      </form>
      {error ? (
        <ErrorState error={error} />
      ) : (
        data && (
          <>
            <div className="discovery-summary" role="status">
              <strong>
                {data.result_count}{" "}
                {data.result_count === 1 ? "result" : "results"} shown
              </strong>
              <span>
                {data.mode === "live"
                  ? `Searched ${data.sources.length} ${data.sources.length === 1 ? "source" : "sources"}`
                  : "Recorded results"}
              </span>
            </div>
            {data.sources.length > 0 && (
              <ul className="source-status" aria-label="Source freshness">
                {data.sources.map((item) => (
                  <li
                    key={item.source}
                    className={
                      item.status === "unavailable" ? "source-warning" : ""
                    }
                  >
                    <strong>{sourceLabel(item.source)}</strong>{" "}
                    {item.status === "success"
                      ? "refreshed for this search"
                      : "temporarily unavailable; recorded results may still appear"}
                  </li>
                ))}
              </ul>
            )}
            <Panel
              title={
                data.mode === "live"
                  ? "Search results"
                  : "Recorded opportunities"
              }
            >
              <TenderTable
                tenders={data.items}
                companyId={company?.id}
                savedIds={saved?.items.map((item) => item.tender.id)}
              />
            </Panel>
            <NextPage
              href={
                data.next_cursor
                  ? `/discover${query({ q: text("q"), source: text("source"), organization: text("organization"), category: text("category"), deadline_before: text("deadline_before"), company_id: company?.id, cursor: data.next_cursor })}`
                  : null
              }
            />
          </>
        )
      )}
    </>
  );
}
