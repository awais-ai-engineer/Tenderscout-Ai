import Link from "next/link";
import { api, query } from "@/lib/api";
import { date, label, positive } from "@/lib/format";
import { Empty, Heading, NextPage, Panel } from "@/components/ui";
import { ReadAlertButton } from "@/components/read-alert-button";
export const dynamic = "force-dynamic";
export default async function AlertsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  const companies = await api.companies();
  const company =
    companies.items.find((c) => c.id === Number(search.company_id)) ||
    companies.items[0];
  const unread = search.unread === "1";
  const data = company
    ? await api.alerts(company.id, unread, positive(search.cursor))
    : null;
  return (
    <>
      <Heading eyebrow="Stay informed" title="Alerts">
        Durable updates for matches, tracked tenders, and approaching deadlines.
      </Heading>
      <form className="filters">
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
        <label>
          <input
            type="checkbox"
            name="unread"
            value="1"
            defaultChecked={unread}
          />{" "}
          Unread only
        </label>
        <button disabled={!company}>Apply</button>
      </form>
      <Panel title="Recent alerts">
        {data?.items.length ? (
          <ul className="record-list">
            {data.items.map((a) => (
              <li key={a.id}>
                <div>
                  <Link href={`/tenders/${a.tender_id}`}>
                    {a.title}: {a.tender_title}
                  </Link>
                  <small>
                    {label(a.type)} · {a.company_name} ·{" "}
                    {date(a.created_at, true)}
                  </small>
                  <small>{a.message}</small>
                </div>
                {a.read_at ? (
                  <span>Read</span>
                ) : (
                  <ReadAlertButton companyId={a.company_id} alertId={a.id} />
                )}
              </li>
            ))}
          </ul>
        ) : (
          <Empty title={company ? "No alerts" : "Add a company profile first"}>
            Qualifying matches and tracked tender events will appear here.
          </Empty>
        )}
      </Panel>
      <NextPage
        href={
          data?.next_cursor
            ? `/alerts${query({ company_id: company?.id, unread: unread ? 1 : undefined, cursor: data.next_cursor })}`
            : null
        }
      />
    </>
  );
}
