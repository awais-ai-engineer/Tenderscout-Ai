import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { label, positive } from "@/lib/format";
import {
  Badge,
  Empty,
  ErrorState,
  Facts,
  Heading,
  NextPage,
  Panel,
  SafeLink,
} from "@/components/ui";
export const dynamic = "force-dynamic";
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
  let company, matches;
  try {
    [company, matches] = await Promise.all([
      api.company(id),
      api.matches("companies", id, positive(search.cursor)),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ErrorState error={error} />;
  }
  const { capabilities, certifications, experience, ...profile } =
    company.profile;
  return (
    <>
      <Link className="back-link" href="/companies">
        ← Company profiles
      </Link>
      <Heading eyebrow="Company-provided profile" title={profile.name}>
        These facts are supplied by the company and have not been independently
        verified.
      </Heading>
      <Panel title="Company facts">
        <div className="panel-body">
          <Facts value={profile} />
          <SafeLink href={profile.website}>Visit company website</SafeLink>
        </div>
      </Panel>
      {Object.entries({ capabilities, certifications, experience }).map(
        ([name, items]) => (
          <Panel title={label(name)} key={name}>
            {items.length ? (
              items.map((item, index) => (
                <div className="fact-card" key={index}>
                  <Facts value={item} />
                </div>
              ))
            ) : (
              <p className="panel-body muted">
                No records supplied. Completeness:{" "}
                {profile[
                  `${name}_complete` as
                    | "capabilities_complete"
                    | "certifications_complete"
                    | "experience_complete"
                ]
                  ? "Asserted complete"
                  : "Not asserted"}
                .
              </p>
            )}
          </Panel>
        ),
      )}
      <Panel title="Saved tender matches">
        {matches.items.length ? (
          <ul className="record-list">
            {matches.items.map((match) => (
              <li key={match.match_id}>
                <Link href={`/matches/${match.match_id}`}>
                  Analysis #{match.analysis_id} · Heuristic alignment{" "}
                  {match.score ?? "not available"} · Coverage{" "}
                  {Math.round(match.coverage_ratio * 100)}%
                </Link>
                <Badge value={match.eligibility_status} />
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="No saved matches">
            Open a tender with a completed analysis to compare this profile.
          </Empty>
        )}
      </Panel>
      <NextPage
        href={
          matches.next_cursor
            ? `/companies/${id}?cursor=${matches.next_cursor}`
            : null
        }
      />
    </>
  );
}
