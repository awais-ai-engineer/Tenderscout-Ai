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
  try {
    data = await api.discover(filters);
  } catch (err) {
    error = err;
  }
  return (
    <>
      <Heading eyebrow="Opportunity discovery" title="Discover opportunities">
        Search Contracts Finder and Find a Tender, compare deadlines, and review
        source evidence. A search refreshes a bounded public listing from each
        selected source; browsing without a query uses recorded opportunities.
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
          <label htmlFor="source">Source</label>
          <select id="source" name="source" defaultValue={text("source")}>
            <option value="">All sources</option>
            <option value="contracts-finder">Contracts Finder</option>
            <option value="find-a-tender">Find a Tender</option>
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
                {data.result_count} {data.result_count === 1 ? "result" : "results"} shown
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
                    className={item.status === "unavailable" ? "source-warning" : ""}
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
              title={data.mode === "live" ? "Search results" : "Recorded opportunities"}
            >
              <TenderTable tenders={data.items} />
            </Panel>
            <NextPage
              href={
                data.next_cursor
                  ? `/discover${query({ source: text("source"), deadline_before: text("deadline_before"), cursor: data.next_cursor })}`
                  : null
              }
            />
          </>
        )
      )}
    </>
  );
}
