import Link from "next/link";
import { api } from "@/lib/api";
import { date } from "@/lib/format";
import { Empty, ErrorState, Heading, Panel } from "@/components/ui";
export const dynamic = "force-dynamic";
export default async function OverviewPage() {
  let data;
  try {
    data = await api.dashboard();
  } catch (error) {
    return (
      <>
        <Heading title="Overview">
          Your recorded opportunities, upcoming deadlines, and recent changes.
        </Heading>
        <ErrorState error={error} />
      </>
    );
  }
  return (
    <>
      <Heading
        title="Overview"
        action={
          <Link className="button" href="/discover">
            Discover opportunities <span aria-hidden="true">↗</span>
          </Link>
        }
      >
        Your recorded opportunities, upcoming deadlines, and recent changes.
      </Heading>
      <section className="intro-banner">
        <div>
          <p className="eyebrow">FROM DISCOVERY TO EVIDENCE</p>
          <h2>Make sense of your next opportunity.</h2>
          <p>
            Review tender requirements, track changes, and keep the source
            close.
          </p>
        </div>
        <span className="banner-symbol" aria-hidden="true">
          ↗
        </span>
      </section>
      <div className="stats">
        <div>
          <p>Upcoming tenders</p>
          <strong>{data.active_tenders_count.toLocaleString()}</strong>
          <small>Known deadline has not passed</small>
        </div>
        <div>
          <p>Recorded tenders</p>
          <strong>{data.tender_count.toLocaleString()}</strong>
          <small>Across connected procurement sources</small>
        </div>
        <div>
          <p>Company matches</p>
          <strong>{data.matching_opportunities_count.toLocaleString()}</strong>
          <small>Explainable stored evaluations</small>
        </div>
        <div>
          <p>Saved tenders</p>
          <strong>{data.saved_tenders_count.toLocaleString()}</strong>
          <small>Tracked across company profiles</small>
        </div>
        <div>
          <p>Unread alerts</p>
          <strong>{data.unread_alerts_count.toLocaleString()}</strong>
          <small>Match, update, and deadline events</small>
        </div>
      </div>
      <div className="two-columns">
        <Panel
          title="Upcoming deadlines"
          action={
            <Link href="/discover" className="text-link">
              Discover opportunities →
            </Link>
          }
        >
          {data.upcoming_deadlines.length ? (
            <ul className="record-list">
              {data.upcoming_deadlines.map((tender) => (
                <li key={tender.id}>
                  <div>
                    <Link href={`/tenders/${tender.id}`}>{tender.title}</Link>
                    <small>
                      {tender.organization || "Authority not provided"}
                    </small>
                  </div>
                  <time dateTime={tender.deadline!}>
                    {date(tender.deadline)}
                  </time>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="No upcoming deadlines">
              Tenders with known future deadlines will appear here.
            </Empty>
          )}
        </Panel>
        <Panel title="Recent changes">
          {data.recent_changes.length ? (
            <ul className="record-list">
              {data.recent_changes.map((change) => (
                <li key={`${change.kind}-${change.id}`}>
                  <div>
                    <Link href={`/changes/${change.kind}/${change.id}`}>
                      {change.change_count}{" "}
                      {change.kind === "metadata" ? "metadata" : "document"}{" "}
                      changes
                    </Link>
                    <small>Tender #{change.tender_id}</small>
                  </div>
                  <time>{date(change.created_at)}</time>
                </li>
              ))}
            </ul>
          ) : (
            <Empty title="No recorded changes">
              Recorded revisions and document comparisons will appear here.
            </Empty>
          )}
        </Panel>
      </div>
    </>
  );
}
