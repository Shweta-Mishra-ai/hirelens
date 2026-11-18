import type { Metadata } from "next";
import { company, display } from "@/lib/company";

export const metadata: Metadata = { title: "Contact · HireLens" };

export default function ContactPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold text-content">Contact</h1>
      <dl className="grid gap-3 sm:grid-cols-[10rem_1fr]">
        <dt className="text-content">Company</dt>
        <dd>{display(company.name, "Company legal name")}</dd>
        <dt className="text-content">Email</dt>
        <dd>
          {company.email ? (
            <a className="text-brand-400 hover:underline" href={`mailto:${company.email}`}>
              {company.email}
            </a>
          ) : (
            "[Contact email]"
          )}
        </dd>
        <dt className="text-content">Address</dt>
        <dd>{display(company.address, "Registered business address")}</dd>
      </dl>
      <p>
        For support, billing and privacy requests, email us from your account&apos;s address so we
        can verify it is you. Candidates asking about their own data should contact the
        organisation they applied to, which controls that data.
      </p>
    </>
  );
}
