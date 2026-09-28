import Link from "next/link";
import { api, query } from "@/lib/api";
import { date, positive, source } from "@/lib/format";
import { Empty, Heading, NextPage, Panel } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function MatchesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  const companies = await api.companies();
  const company =
    companies.items.find((item) => item.id === Number(search.company_id)) ||
    companies.items[0];
  const data = company
    ? await api.opportunityMatches(company.id, positive(search.cursor))
    : null;

  return (
    <>
      <Heading eyebrow="Company fit" title="My Matches">
        Explainable alignment based on company facts and tender requirements.
      </Heading>
      <form className="filters">
        <div className="field">
          <label htmlFor="company">Company</label>
          <select id="company" name="company_id" defaultValue={company?.id}>
            {companies.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <button disabled={!company}>View matches</button>
      </form>
      <Panel title="Strongest matches first">
        {data?.items.length ? (
          <ul className="record-list">
            {data.items.map((match) => (
              <li key={match.match_id}>
                <div>
                  <Link href={`/tenders/${match.tender_id}?tab=matches`}>
                    {match.tender_title}
                  </Link>
                  <small>
                    {match.organization || "Authority not provided"} ·{" "}
                    {source(match.source)} · Deadline {date(match.deadline)}
                  </small>
                  <small>
                    {match.matched_reasons.slice(0, 2).join(" · ") ||
                      "No confirmed reason recorded"}
                    {match.unknown_reasons.length > 0 &&
                      ` · Needs review: ${match.unknown_reasons[0]}`}
                  </small>
                </div>
                <strong>
                  {match.score === null
                    ? "Needs review"
                    : `${match.score}/100 fit`}
                </strong>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No company matches">
            Matches appear after a supported tender analysis is evaluated.
          </Empty>
        )}
      </Panel>
      <NextPage
        href={
          data?.next_cursor
            ? `/matches${query({ company_id: company?.id, cursor: data.next_cursor })}`
            : null
        }
      />
    </>
  );
}
