import Link from "next/link";
import { api } from "@/lib/api";
import { positive } from "@/lib/format";
import { Empty, ErrorState, Heading, NextPage, Panel } from "@/components/ui";
export const dynamic = "force-dynamic";
export default async function CompaniesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  let data, error;
  try {
    data = await api.companies(positive(params.cursor));
  } catch (err) {
    error = err;
  }
  return (
    <>
      <Heading
        eyebrow="Company intelligence"
        title="Company profiles"
        action={
          <Link className="button" href="/companies/new">
            + Add company
          </Link>
        }
      >
        Record company-provided facts for transparent tender comparisons.
      </Heading>
      {error ? (
        <ErrorState error={error} />
      ) : (
        data && (
          <>
            <Panel title="Your profiles">
              {data.items.length ? (
                data.items.map((company) => (
                  <article className="company-card" key={company.id}>
                    <h3>
                      <Link href={`/companies/${company.id}`}>
                        {company.name} →
                      </Link>
                    </h3>
                    <p>
                      {company.country || "Country not provided"} ·
                      Company-provided profile
                    </p>
                    <div className="inline-actions">
                      <span>{company.capability_count} capabilities</span>
                      <span>{company.certification_count} certifications</span>
                      <span>{company.experience_count} experience records</span>
                    </div>
                    <p>
                      Completeness asserted:{" "}
                      {[
                        company.capabilities_complete && "capabilities",
                        company.certifications_complete && "certifications",
                        company.experience_complete && "experience",
                        company.financials_complete && "financials",
                      ]
                        .filter(Boolean)
                        .join(", ") || "None"}
                    </p>
                  </article>
                ))
              ) : (
                <Empty title="No company profiles">
                  Add your company facts to start comparing requirements.
                </Empty>
              )}
            </Panel>
            <NextPage
              href={
                data.next_cursor
                  ? `/companies?cursor=${data.next_cursor}`
                  : null
              }
            />
          </>
        )
      )}
    </>
  );
}
