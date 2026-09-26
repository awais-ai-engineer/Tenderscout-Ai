import { api } from "@/lib/api";
import { positive } from "@/lib/format";
import {
  ErrorState,
  Heading,
  NextPage,
  Panel,
  RunTable,
} from "@/components/ui";
import { PipelineTrigger } from "@/components/pipeline-trigger";
export const dynamic = "force-dynamic";
export default async function PipelinePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  let data, error;
  try {
    data = await api.runs(positive(params.cursor));
  } catch (err) {
    error = err;
  }
  return (
    <>
      <Heading eyebrow="Processing operations" title="Pipeline activity">
        Follow durable processing stages, attempts, and recorded outcomes.
      </Heading>
      <PipelineTrigger />
      {error ? (
        <ErrorState error={error} />
      ) : (
        data && (
          <>
            <Panel title="Recent source runs">
              <RunTable runs={data.items} />
            </Panel>
            <NextPage
              href={
                data.next_cursor ? `/pipeline?cursor=${data.next_cursor}` : null
              }
            />
          </>
        )
      )}
    </>
  );
}
