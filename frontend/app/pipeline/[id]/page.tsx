import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { positive } from "@/lib/format";
import { ErrorState, Heading } from "@/components/ui";
import { PipelineLive } from "@/components/pipeline-live";
export const dynamic = "force-dynamic";
export default async function RunPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const { id } = await params;
  const search = await searchParams;
  if (!positive(id)) notFound();
  const cursor = positive(search.after_stage_id);
  let run;
  try {
    run = await api.run(id, cursor);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ErrorState error={error} />;
  }
  return (
    <>
      <Link href="/pipeline" className="back-link">
        ← Pipeline activity
      </Link>
      <Heading title={`Source run #${id}`}>
        Database records determine each stage’s status.
      </Heading>
      <PipelineLive
        key={`${id}-${cursor}`}
        initial={run}
        afterStageId={cursor}
      />
    </>
  );
}
