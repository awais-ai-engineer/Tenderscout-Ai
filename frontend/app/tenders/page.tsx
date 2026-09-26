import Link from "next/link";
import { api, query } from "@/lib/api";
import { positive } from "@/lib/format";
import {
  ErrorState,
  Heading,
  NextPage,
  Panel,
  TenderTable,
} from "@/components/ui";
export const dynamic = "force-dynamic";
export default async function TendersPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const text = (name: string) =>
    typeof params[name] === "string" ? params[name] : "";
  const filters = {
    search: text("search"),
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
    data = await api.tenders(filters);
  } catch (err) {
    error = err;
  }
  return (
    <>
      <Heading eyebrow="Opportunity discovery" title="Tenders">
        Explore recorded procurement notices and their source evidence.
      </Heading>
      <form className="filters" action="/tenders">
        <div className="field">
          <label htmlFor="search">Search tenders</label>
          <input
            id="search"
            name="search"
            defaultValue={text("search")}
            placeholder="Title or authority…"
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
        <button type="submit">Apply filters</button>
        <Link className="text-link" href="/tenders">
          Reset
        </Link>
      </form>
      {error ? (
        <ErrorState error={error} />
      ) : (
        data && (
          <>
            <Panel title="Recorded opportunities">
              <TenderTable tenders={data.items} />
            </Panel>
            <NextPage
              href={
                data.next_cursor
                  ? `/tenders${query({ search: text("search"), source: text("source"), deadline_before: text("deadline_before"), cursor: data.next_cursor })}`
                  : null
              }
            />
          </>
        )
      )}
    </>
  );
}
