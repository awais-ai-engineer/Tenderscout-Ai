import Link from "next/link";
import { Empty, Heading, Panel } from "@/components/ui";

export default function SavedPage() {
  return <>
    <Heading eyebrow="Your shortlist" title="Saved Tenders">A place for the opportunities you want to revisit.</Heading>
    <Panel title="Saved opportunities">
      <Empty title="Saving is not available yet">Saved opportunities will appear here when this feature is available. You can still browse recorded tenders and their source evidence.</Empty>
      <div className="shell-actions"><Link className="button secondary" href="/discover">Discover opportunities</Link></div>
    </Panel>
  </>;
}
