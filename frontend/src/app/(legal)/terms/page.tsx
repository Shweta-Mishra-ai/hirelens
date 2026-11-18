import type { Metadata } from "next";
import { company, display } from "@/lib/company";

export const metadata: Metadata = { title: "Terms of Service · HireLens" };

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="pt-4 text-base font-semibold text-content">{children}</h2>;
}

export default function TermsPage() {
  const name = display(company.name, "Company legal name");
  const email = display(company.email, "contact email");
  const law = display(company.jurisdiction, "governing law and courts");
  return (
    <>
      <h1 className="text-2xl font-semibold text-content">Terms of Service</h1>
      <p>
        These terms are an agreement between you (or the organisation you act for) and {name}{" "}
        for the use of HireLens. By creating an account you accept them.
      </p>

      <H>The service</H>
      <p>
        HireLens analyses resumes you upload, checks some claims against public sources, and helps
        your team review candidates. Its scores, flags and verification results are signals for a
        person to investigate. They can be wrong, and they are not a decision. You must not use
        HireLens as the sole basis for rejecting or hiring anyone.
      </p>

      <H>Your responsibilities</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>Keep your sign-in details secure; you are responsible for activity on your account.</li>
        <li>
          Only upload data you are entitled to process, with a lawful basis and any notice to
          candidates that the law requires, and comply with employment and anti-discrimination law.
        </li>
        <li>
          Do not upload malicious files, attempt to access other accounts or data, overload the
          service, or resell it without our written agreement.
        </li>
      </ul>

      <H>Plans and payment</H>
      <p>
        Plans include a number of analyses per calendar month, shown in the app. An analysis that
        fails is not counted. Paid plans are billed in advance for each period, and fees are
        exclusive of taxes unless stated. We may change prices with at least 30 days&apos; notice.
        Refunds are covered by the Refund Policy.
      </p>

      <H>Your content</H>
      <p>
        You keep all rights to what you upload and to the reports produced from it. You allow us to
        process it only to provide and secure the service. We do not sell it.
      </p>

      <H>Availability and changes</H>
      <p>
        We aim to keep HireLens available but do not guarantee uninterrupted service. Features may
        change; we will not remove a core feature you pay for during a paid period without notice.
      </p>

      <H>Termination</H>
      <p>
        You may stop using HireLens at any time. We may suspend or close an account that breaches
        these terms. On closure you may export your reports before we delete them.
      </p>

      <H>Disclaimers and liability</H>
      <p>
        The service is provided &quot;as is&quot;. To the extent the law allows, we are not liable
        for indirect or consequential losses, or for decisions made using the service, and our
        total liability is limited to the fees you paid in the twelve months before the claim.
        Nothing here limits liability that cannot be limited by law.
      </p>

      <H>Governing law</H>
      <p>These terms are governed by {law}.</p>

      <H>Contact</H>
      <p>Questions about these terms: {email}.</p>
    </>
  );
}
