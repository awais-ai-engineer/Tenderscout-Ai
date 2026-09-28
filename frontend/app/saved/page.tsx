import Link from "next/link";
import { api, query } from "@/lib/api";
import { date, positive, source } from "@/lib/format";
import { Empty, ErrorState, Heading, NextPage, Panel } from "@/components/ui";
import { SaveButton } from "@/components/save-button";
export const dynamic = "force-dynamic";
export default async function SavedPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  const companies = await api.companies();
  const requested = Number(
    typeof search.company_id === "string" ? search.company_id : 0,
  );
  const company =
    companies.items.find((c) => c.id === requested) || companies.items[0];
  let data, error;
  if (company)
    try {
      data = await api.saved(company.id, positive(search.cursor));
    } catch (e) {
      error = e;
    }
  return (
    <>
      <Heading eyebrow="Your shortlist" title="Saved Tenders">
        Track opportunities for a company profile.
      </Heading>
      <form className="filters" action="/saved">
        <div className="field">
          <label htmlFor="company">Company</label>
          <select id="company" name="company_id" defaultValue={company?.id}>
            {companies.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <button disabled={!company}>View saved</button>
      </form>
      {error ? (
        <ErrorState error={error} />
      ) : (
        <Panel title="Saved opportunities">
          {data?.items.length ? (
            <ul className="record-list">
              {data.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <Link
                      href={`/tenders/${item.tender.id}?company_id=${company!.id}`}
                    >
                      {item.tender.title}
                    </Link>
                    <small>
                      {item.tender.organization || "Authority not provided"} ·{" "}
                      {source(item.tender.source)} · Saved {date(item.saved_at)}
                      {item.updated_since_saved ? " · Updated since saved" : ""}
                    </small>
                  </div>
                  <span>
                    {date(item.tender.deadline)}{" "}
                    <SaveButton
                      companyId={company!.id}
                      tenderId={item.tender.id}
                      initial
                    />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty
              title={
                company ? "No saved tenders" : "Add a company profile first"
              }
            >
              Save opportunities from Discover or a tender detail page.
            </Empty>
          )}
        </Panel>
      )}
      <NextPage
        href={
          data?.next_cursor
            ? `/saved${query({ company_id: company?.id, cursor: data.next_cursor })}`
            : null
        }
      />
    </>
  );
}
