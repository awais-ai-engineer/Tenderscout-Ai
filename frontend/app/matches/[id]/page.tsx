import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { positive } from "@/lib/format";
import { Heading, ErrorState } from "@/components/ui";
import { MatchView } from "@/components/match-view";
export const dynamic = "force-dynamic";
export default async function MatchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!positive(id)) notFound();
  let match;
  try {
    match = await api.match(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ErrorState error={error} />;
  }
  return (
    <>
      <Link className="back-link" href={`/companies/${match.company_id}`}>
        ← Company profile
      </Link>
      <Heading title="Explainable match">
        Recorded comparison #{match.match_id}. Source requirements and company
        facts remain visible.
      </Heading>
      <MatchView match={match} />
    </>
  );
}
