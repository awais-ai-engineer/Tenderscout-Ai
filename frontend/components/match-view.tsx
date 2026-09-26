import type { Match } from "@/lib/types";
import { label } from "@/lib/format";
import { Badge, Facts, Panel } from "./ui";
export function MatchView({ match }: { match: Match }) {
  const sections = {
    hard_blockers: match.hard_blockers,
    matched_requirements: match.matched_requirements,
    unmatched_requirements: match.unmatched_requirements,
    unknown_requirements: match.unknown_requirements,
    capability_matches: match.capability_matches,
    certification_matches: match.certification_matches,
    experience_matches: match.experience_matches,
  };
  return (
    <>
      <div className="stats">
        <div>
          <p>Eligibility</p>
          <Badge value={match.eligibility_status} />
          <small>Based on recorded facts</small>
        </div>
        <div>
          <p>Heuristic alignment score</p>
          <strong>
            {match.score === null ? "Not available" : `${match.score}/100`}
          </strong>
          <small>Not a prediction of procurement outcome</small>
        </div>
        <div>
          <p>Evidence coverage</p>
          <strong>{Math.round(match.coverage_ratio * 100)}%</strong>
          <small>Requirements with comparable facts</small>
        </div>
      </div>
      <p className="helper">
        Company #{match.company_id} · Analysis #{match.analysis_id}. Company
        facts are user assertions, not independently verified.
      </p>
      {Object.entries(sections).map(([name, records]) => (
        <Panel title={label(name)} key={name}>
          {records.length ? (
            records.map((item, index) => (
              <article className="fact-card" key={index}>
                <p>
                  <strong>{item.requirement}</strong>
                </p>
                <Badge value={item.status} />
                <p>{item.reason}</p>
                <details>
                  <summary>Comparison facts and evidence</summary>
                  <h3>Company fact</h3>
                  <Facts value={item.company_fact} />
                  <blockquote>{item.tender_evidence}</blockquote>
                </details>
              </article>
            ))
          ) : (
            <p className="panel-body muted">None recorded.</p>
          )}
        </Panel>
      ))}
      <Panel title="Risks and review notes">
        {match.risks.map((risk, index) => (
          <article className="fact-card" key={index}>
            <p>{risk.reason}</p>
            {risk.tender_evidence && (
              <blockquote>{risk.tender_evidence}</blockquote>
            )}
          </article>
        ))}
      </Panel>
    </>
  );
}
