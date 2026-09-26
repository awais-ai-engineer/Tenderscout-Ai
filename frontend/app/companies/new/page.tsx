import Link from "next/link";
import { CompanyForm } from "@/components/company-form";
import { Heading } from "@/components/ui";
export default function NewCompanyPage() {
  return (
    <>
      <Link href="/companies" className="back-link">
        ← Company profiles
      </Link>
      <Heading title="Add company profile">
        Record the facts you can support. Unknown information can remain blank.
      </Heading>
      <CompanyForm />
    </>
  );
}
