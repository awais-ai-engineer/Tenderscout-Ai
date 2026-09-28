import { api } from "@/lib/api";
import { Empty, Heading, Panel } from "@/components/ui";
import { NotificationForm } from "@/components/notification-form";
export const dynamic = "force-dynamic";
export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  const companies = await api.companies();
  const company =
    companies.items.find((c) => c.id === Number(search.company_id)) ||
    companies.items[0];
  const preferences = company ? await api.preferences(company.id) : null;
  return (
    <>
      <Heading eyebrow="Your workspace" title="Settings">
        Configure notifications for a company profile.
      </Heading>
      <form className="filters">
        <div className="field">
          <label htmlFor="company">Company</label>
          <select id="company" name="company_id" defaultValue={company?.id}>
            {companies.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        <button disabled={!company}>Edit settings</button>
      </form>
      <Panel title="Notifications">
        {preferences ? (
          <NotificationForm initial={preferences} />
        ) : (
          <Empty title="Add a company profile first">
            Notification preferences are company scoped.
          </Empty>
        )}
      </Panel>
    </>
  );
}
