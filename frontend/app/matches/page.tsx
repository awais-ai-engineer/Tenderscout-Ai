import Link from "next/link";
import { Empty, Heading, Panel } from "@/components/ui";

export default function MatchesPage() {
  return <>
    <Heading eyebrow="Company fit" title="My Matches">Review opportunities against your company profile and the evidence in each tender.</Heading>
    <Panel title="Company matches">
      <Empty title="Match overview coming soon">Add a company profile and analyze opportunities to see matches. For now, open an analyzed tender and choose a company in its Matches tab.</Empty>
      <div className="shell-actions"><Link className="button" href="/companies">View companies</Link><Link className="button secondary" href="/discover">Discover opportunities</Link></div>
    </Panel>
  </>;
}
