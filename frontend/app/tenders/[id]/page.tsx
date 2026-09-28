import Link from "next/link";
import { notFound } from "next/navigation";
import { api, ApiError, query } from "@/lib/api";
import { date, positive, source } from "@/lib/format";
import { AnalysisView } from "@/components/analysis-view";
import { AskForm } from "@/components/ask-form";
import { DocumentCard } from "@/components/document-list";
import { MatchForm } from "@/components/match-form";
import { SaveButton } from "@/components/save-button";
import {
  Badge,
  Empty,
  ErrorState,
  Heading,
  NextPage,
  Panel,
  SafeLink,
} from "@/components/ui";
export const dynamic = "force-dynamic";
const tabs = ["overview", "analysis", "documents", "changes", "ask", "matches"];
export default async function TenderPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  if (!positive(id)) notFound();
  const search = await searchParams;
  const tab =
    typeof search.tab === "string" && tabs.includes(search.tab)
      ? search.tab
      : "overview";
  let tender;
  try {
    tender = await api.tender(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return <ErrorState error={error} />;
  }
  let content;
  try {
    content = await renderTab(id, tab, search, tender);
  } catch (error) {
    content = <ErrorState error={error} />;
  }
  const companies = await api.companies();
  const selectedCompany =
    companies.items.find((item) => item.id === positive(search.company_id)) ||
    companies.items[0];
  const saved = selectedCompany
    ? await api.saved(selectedCompany.id).catch(() => null)
    : null;
  return (
    <>
      <Link className="back-link" href="/discover">
        ← Discover opportunities
      </Link>
      <Heading eyebrow={source(tender.source)} title={tender.title}>
        {tender.organization || "Authority not provided"} ·{" "}
        {tender.category || "Category not provided"}
      </Heading>
      {selectedCompany && (
        <div className="shell-actions">
          <SaveButton
            companyId={selectedCompany.id}
            tenderId={tender.id}
            initial={Boolean(
              saved?.items.some((item) => item.tender.id === tender.id),
            )}
          />
          <small>Tracked for {selectedCompany.name}</small>
        </div>
      )}
      <nav className="tabs" aria-label="Tender sections">
        {tabs.map((item) => (
          <Link
            className={item === tab ? "active" : ""}
            aria-current={item === tab ? "page" : undefined}
            key={item}
            href={`/tenders/${id}?tab=${item}`}
          >
            {item === "ask"
              ? "Ask Tender"
              : item[0].toUpperCase() + item.slice(1)}
          </Link>
        ))}
      </nav>
      {content}
    </>
  );
}

async function renderTab(
  id: string,
  tab: string,
  search: Record<string, string | string[] | undefined>,
  tender: Awaited<ReturnType<typeof api.tender>>,
) {
  const href = (values: Record<string, string | number | undefined>) =>
    `/tenders/${id}${query({ tab, ...values })}`;
  let content;
  if (tab === "overview")
    content = (
      <>
        <Panel title="Tender overview">
          <dl className="details-grid">
            {[
              ["Authority", tender.organization],
              ["Source", source(tender.source)],
              ["Category", tender.category],
              ["Location", tender.location],
              ["Published", date(tender.published_at)],
              ["Deadline", date(tender.deadline, true)],
              ["Last observed", date(tender.last_seen_at, true)],
              ["Recorded revisions", String(tender.latest_revision_index)],
              ["External reference", tender.external_id],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || "Not provided"}</dd>
              </div>
            ))}
          </dl>
          <div className="panel-body">
            <SafeLink href={tender.source_url}>Open source notice</SafeLink>
          </div>
        </Panel>
        <Panel title="Description">
          <div className="panel-body">
            <p className="prose">
              {tender.description || "No description has been recorded."}
            </p>
            {tender.description_truncated && (
              <p className="helper">
                Preview limited to 20,000 characters. Consult the source notice
                for the full text.
              </p>
            )}
          </div>
        </Panel>
      </>
    );
  if (tab === "documents") {
    const docs = await api.documents(id, positive(search.cursor));
    content = (
      <>
        {docs.items.length ? (
          docs.items.map((doc) => <DocumentCard key={doc.id} document={doc} />)
        ) : (
          <Empty title="No documents recorded">
            Document discovery is currently supported for Contracts Finder.
          </Empty>
        )}
        <NextPage
          href={docs.next_cursor ? href({ cursor: docs.next_cursor }) : null}
        />
      </>
    );
  }
  if (tab === "analysis" || tab === "matches") {
    const analyses = positive(search.analysis_cursor)
      ? await api.analyses(id, positive(search.analysis_cursor))
      : tender.analyses;
    const completed = analyses.items.filter(
      (item) => item.status === "completed",
    );
    const selected =
      completed.find((item) => item.id === positive(search.analysis)) ||
      completed[0];
    const selector = (
      <>
        <form className="filters" action={`/tenders/${id}`}>
          <input type="hidden" name="tab" value={tab} />
          {search.analysis_cursor && (
            <input
              type="hidden"
              name="analysis_cursor"
              value={String(search.analysis_cursor)}
            />
          )}
          <div className="field">
            <label htmlFor="analysis">Recorded analysis</label>
            <select name="analysis" id="analysis" defaultValue={selected?.id}>
              {completed.map((item) => (
                <option key={item.id} value={item.id}>
                  Analysis #{item.id} · Version #{item.document_version_id} ·{" "}
                  {date(item.created_at)}
                </option>
              ))}
            </select>
          </div>
          <button disabled={!selected}>View analysis</button>
        </form>
        <NextPage
          href={
            analyses.next_cursor
              ? href({ analysis_cursor: analyses.next_cursor })
              : null
          }
        />
      </>
    );
    if (tab === "analysis")
      content = (
        <>
          {selector}
          {selected ? (
            <AnalysisView analysis={await api.analysis(selected.id)} />
          ) : (
            <Empty title="No completed analysis">
              An extracted document needs a supported completed analysis before
              facts can be displayed.
            </Empty>
          )}
        </>
      );
    else {
      const matches = await api.matches("tenders", id, positive(search.cursor));
      content = (
        <>
          {selector}
          {selected ? (
            <MatchForm
              key={selected.id}
              analysisId={selected.id}
              initial={await api.companies()}
            />
          ) : (
            <Empty title="Matching needs an analysis">
              Complete a document analysis before comparing company facts.
            </Empty>
          )}
          <Panel title="Saved matches">
            {matches.items.length ? (
              <ul className="record-list">
                {matches.items.map((match) => (
                  <li key={match.match_id}>
                    <Link href={`/matches/${match.match_id}`}>
                      Company #{match.company_id} · Analysis #
                      {match.analysis_id}
                    </Link>
                    <Badge value={match.eligibility_status} />
                  </li>
                ))}
              </ul>
            ) : (
              <Empty title="No saved matches">
                Compare a company profile to create an explainable match.
              </Empty>
            )}
          </Panel>
          <NextPage
            href={
              matches.next_cursor ? href({ cursor: matches.next_cursor }) : null
            }
          />
        </>
      );
    }
  }
  if (tab === "changes") {
    const [metadata, documents, revisions] = await Promise.all([
      api.changes(id, "metadata", positive(search.metadata_cursor)),
      api.changes(id, "document", positive(search.document_cursor)),
      api.revisions(id, positive(search.revision_cursor)),
    ]);
    content = (
      <>
        {[
          ["Metadata changes", metadata, "metadata_cursor"],
          ["Document analysis changes", documents, "document_cursor"],
        ].map(([title, data, cursorKey]) => {
          const page = data as typeof metadata;
          return (
            <Panel key={String(title)} title={String(title)}>
              {page.items.length ? (
                <ul className="record-list">
                  {page.items.map((change) => (
                    <li key={change.id}>
                      <Link href={`/changes/${change.kind}/${change.id}`}>
                        {change.change_count} recorded changes · Comparison #
                        {change.id}
                      </Link>
                      <time>{date(change.created_at, true)}</time>
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty title="No changes recorded">
                  Only stored comparisons are shown here.
                </Empty>
              )}
              <NextPage
                href={
                  page.next_cursor
                    ? href({ [String(cursorKey)]: page.next_cursor })
                    : null
                }
              />
            </Panel>
          );
        })}
        <Panel title="Metadata revision history">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Revision</th>
                  <th>Observed (UTC)</th>
                  <th>Deadline (UTC)</th>
                  <th>Snapshot hash</th>
                </tr>
              </thead>
              <tbody>
                {revisions.items.map((revision) => (
                  <tr key={revision.revision_id}>
                    <td>#{revision.revision_index}</td>
                    <td>{date(revision.observed_at, true)}</td>
                    <td>{date(revision.deadline, true)}</td>
                    <td>{revision.snapshot_hash.slice(0, 16)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!revisions.items.length && (
            <Empty>No revision baseline has been captured yet.</Empty>
          )}
          <NextPage
            href={
              revisions.next_cursor
                ? href({ revision_cursor: revisions.next_cursor })
                : null
            }
          />
        </Panel>
      </>
    );
  }
  if (tab === "ask") {
    const docs = await api.documents(id, positive(search.document_cursor));
    const document =
      docs.items.find((item) => item.id === positive(search.document)) ||
      docs.items[0];
    const versions = document
      ? await api.versions(document.id, positive(search.version_cursor))
      : null;
    const version =
      versions?.items.find((item) => item.id === positive(search.version)) ||
      versions?.items[0];
    content = (
      <>
        <form className="filters" action={`/tenders/${id}`}>
          <input type="hidden" name="tab" value="ask" />
          {search.document_cursor && (
            <input
              type="hidden"
              name="document_cursor"
              value={String(search.document_cursor)}
            />
          )}
          <div className="field">
            <label htmlFor="document">Document</label>
            <select id="document" name="document" defaultValue={document?.id}>
              {docs.items.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.title || `Document #${doc.id}`}
                </option>
              ))}
            </select>
          </div>
          <button disabled={!document}>Select document</button>
        </form>
        <NextPage
          href={
            docs.next_cursor
              ? href({ document_cursor: docs.next_cursor })
              : null
          }
        />
        {versions && document && (
          <>
            <form className="filters" action={`/tenders/${id}`}>
              <input type="hidden" name="tab" value="ask" />
              <input type="hidden" name="document" value={document.id} />
              {search.document_cursor && (
                <input
                  type="hidden"
                  name="document_cursor"
                  value={String(search.document_cursor)}
                />
              )}
              <input
                type="hidden"
                name="version_cursor"
                value={String(search.version_cursor || "")}
              />
              <div className="field">
                <label htmlFor="version">Document version</label>
                <select name="version" id="version" defaultValue={version?.id}>
                  {versions.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      Version #{item.id} · {date(item.downloaded_at)} ·{" "}
                      {item.is_indexed ? "Indexed" : "Not indexed"}
                    </option>
                  ))}
                </select>
              </div>
              <button disabled={!version}>Use version</button>
            </form>
            <NextPage
              href={
                versions.next_cursor
                  ? href({
                      document: document.id,
                      document_cursor: positive(search.document_cursor),
                      version_cursor: versions.next_cursor,
                    })
                  : null
              }
            />
          </>
        )}
        {version?.is_indexed ? (
          <AskForm key={version.id} versionId={version.id} />
        ) : (
          <Empty title="No indexed document selected">
            Select a version fully indexed for the configured embedding model.
            Questions remain scoped to that version.
          </Empty>
        )}
      </>
    );
  }

  return content;
}
