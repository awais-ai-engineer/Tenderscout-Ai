import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { date, label, positive } from "@/lib/format";
import {
  Badge,
  Empty,
  ErrorState,
  Facts,
  Heading,
  Panel,
} from "@/components/ui";
export const dynamic = "force-dynamic";
export default async function ChangePage({
  params,
}: {
  params: Promise<{ kind: string; id: string }>;
}) {
  const { kind, id } = await params;
  if (!["metadata", "document"].includes(kind) || !positive(id)) notFound();
  let change;
  try {
    change = await api.change(kind, id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ErrorState error={error} />;
  }
  return (
    <>
      <Link
        className="back-link"
        href={`/tenders/${change.tender_id}?tab=changes`}
      >
        ← Tender change history
      </Link>
      <Heading
        title={
          kind === "metadata"
            ? "Metadata comparison"
            : "Document analysis comparison"
        }
      >
        Record #{change.from_id} → #{change.to_id} · {change.change_count}{" "}
        changes · {date(change.created_at, true)}
      </Heading>
      <p className="notice">
        Recorded differences preserve source facts. Lexical pairings require
        review and do not establish legal impact.
      </p>
      {change.changes.length ? (
        change.changes.map((item, index) => (
          <Panel
            key={index}
            title={label(item.field || item.category || "Change")}
            action={<Badge value={item.change_type} />}
          >
            <div className="panel-body">
              <div className="old-new">
                <div>
                  <h3>Previous</h3>
                  <Facts value={item.old ?? item.old_preview} />
                  {item.old_hash && (
                    <small className="helper">
                      Hash: {item.old_hash.slice(0, 16)}
                    </small>
                  )}
                </div>
                <div>
                  <h3>Updated</h3>
                  <Facts value={item.new ?? item.new_preview} />
                  {item.new_hash && (
                    <small className="helper">
                      Hash: {item.new_hash.slice(0, 16)}
                    </small>
                  )}
                </div>
              </div>
              {item.requires_review && (
                <p className="alert-line">
                  Review required ·{" "}
                  {label(item.match_basis || "lexical pairing")}
                </p>
              )}
            </div>
          </Panel>
        ))
      ) : (
        <Empty title="No recorded differences">
          These inputs produced an unchanged comparison.
        </Empty>
      )}
    </>
  );
}
