import Link from "next/link";
import { Heading, Panel } from "@/components/ui";

export default function SettingsPage() {
  return <>
    <Heading eyebrow="Your workspace" title="Settings">A preview of the preferences planned for TenderScout.</Heading>
    <div className="settings-grid">
      <Panel title="Company & discovery preferences"><div className="panel-body"><p>Preference controls are not available yet. You can manage existing company profiles now.</p><Link className="text-link" href="/companies">View companies →</Link></div></Panel>
      <Panel title="Notifications"><div className="panel-body"><p>Alert and notification settings are planned. No delivery preferences are active here.</p></div></Panel>
      <Panel title="Data & product preferences"><div className="panel-body"><p>Data and product settings are planned. There are no editable controls on this page yet.</p></div></Panel>
    </div>
  </>;
}
