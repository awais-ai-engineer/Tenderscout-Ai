import type { Analysis } from "@/lib/types";
import { label } from "@/lib/format";
import { Empty, Facts, Panel } from "./ui";
export function AnalysisView({ analysis }: { analysis: Analysis }) {
  if (!analysis.facts)
    return (
      <Empty title="No supported structured analysis">
        This analysis is failed or uses an unsupported schema.
      </Empty>
    );
  const { summary, summary_evidence, ...categories } = analysis.facts;
  return (
    <>
      <p className="helper">
        Analysis #{analysis.id} · Document version #
        {analysis.document_version_id} · Source evidence is retained beneath
        each fact.
      </p>
      {summary && (
        <Panel title="Summary">
          <div className="panel-body">
            <p>{summary}</p>
            {summary_evidence.map((quote, index) => (
              <blockquote key={index}>{quote}</blockquote>
            ))}
          </div>
        </Panel>
      )}
      {Object.entries(categories).map(([category, facts]) => (
        <Panel title={label(category)} key={category}>
          {facts.length ? (
            facts.map((fact, index) => {
              const { evidence, ...values } = fact;
              return (
                <article className="fact-card" key={index}>
                  <Facts value={values} />
                  <details>
                    <summary>Source evidence</summary>
                    <blockquote>{evidence}</blockquote>
                  </details>
                </article>
              );
            })
          ) : (
            <div className="panel-body muted">
              No facts recorded in this category.
            </div>
          )}
        </Panel>
      ))}
    </>
  );
}
