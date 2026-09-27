import { Empty, Heading, Panel } from "@/components/ui";

export default function AlertsPage() {
  return <>
    <Heading eyebrow="Stay informed" title="Alerts">Planned notifications for changes to opportunities that matter to you.</Heading>
    <Panel title="Alert preferences">
      <Empty title="Alerts are not available yet">Notification setup and delivery are planned. No alerts are currently being sent from this page.</Empty>
      <ul className="planned-list" aria-label="Planned alert types">
        <li><span>New matching opportunities</span><small>Planned</small></li>
        <li><span>Tender changes</span><small>Planned</small></li>
        <li><span>Deadline reminders</span><small>Planned</small></li>
      </ul>
    </Panel>
  </>;
}
