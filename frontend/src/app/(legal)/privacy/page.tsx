import type { Metadata } from "next";
import { company, display } from "@/lib/company";

export const metadata: Metadata = { title: "Privacy Policy" };

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="pt-4 text-base font-semibold text-content">{children}</h2>;
}

export default function PrivacyPage() {
  const name = display(company.name, "Company legal name");
  const email = display(company.email, "privacy contact email");
  return (
    <>
      <h1 className="text-2xl font-semibold text-content">Privacy Policy</h1>
      <p>
        This policy explains what personal data {name} (&quot;we&quot;) handles when you use
        HireLens, why, who else receives it, and the choices you have. Contact: {email}
        {company.address ? `, ${company.address}` : ""}.
      </p>

      <H>Two kinds of personal data, two roles</H>
      <p>
        <strong className="text-content">Your account.</strong> When you sign up we hold your name,
        email address, company name and a password that is stored only as a one-way hash. For this
        data we are the controller.
      </p>
      <p>
        <strong className="text-content">Candidates in the resumes you upload.</strong> Resumes
        contain other people&apos;s personal data — names, contact details, employment and education
        history. Your organisation decides why that data is processed and is its controller; we
        process it on your instructions to provide the service. You must have a lawful basis for
        uploading it, and candidates should direct requests about their data to the organisation
        they applied to.
      </p>

      <H>What we process and why</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>Resume text, to produce the credibility analysis you request.</li>
        <li>
          Details from the resume — a GitHub username, institution names, certificate links,
          employer names — to check them against public sources when you run verification.
        </li>
        <li>Job descriptions you paste or save, to rank candidates against a role.</li>
        <li>Your decisions, interview notes, comments and votes, to show them to you and your team.</li>
        <li>Candidate email addresses, only to send a message when you choose to send one.</li>
        <li>
          Usage counts (analyses per month) for plan limits, and technical data — IP address and
          request logs — to keep the service secure and to rate-limit abuse.
        </li>
      </ul>
      <p>
        HireLens produces decision support. It does not make hiring decisions, and its output must
        be reviewed by a person before it is acted on.
      </p>

      <H>Who else receives data (sub-processors)</H>
      <ul className="list-disc space-y-1 pl-5">
        <li>Supabase — database and sign-in.</li>
        <li>
          Render — hosts the API. {display(company.websiteHost, "website host, e.g. Netlify")} —
          hosts this website.
        </li>
        <li>
          AI providers — resume text is sent to one or more of Google (Gemini API), Groq and
          Anthropic to be analysed. Before it is sent, email addresses, phone numbers, web links
          and — where it can be identified from the resume&apos;s heading — the candidate&apos;s name
          are replaced with placeholders, and restored only on our servers. Work and education
          history is sent, because that is what is analysed. The providers&apos; terms differ: when
          Google&apos;s Gemini API is used without billing enabled, Google&apos;s terms allow it to use
          submitted content to improve its products, including review by people; its paid tier,
          Groq and Anthropic do not use API content for training under their published terms.
        </li>
        <li>An email provider (Resend or an SMTP service) — for messages you choose to send.</li>
        <li>
          Public sources used by verification — GitHub, a public university registry, and the
          websites behind certificate links and employer names.
        </li>
      </ul>

      <H>How long we keep it</H>
      <p>
        Reports, notes and comments are kept until you delete them or your account is closed.
        Deleting a report deletes its comments and votes. Usage counts are kept for billing.
        Request logs are kept by our hosting providers for their standard retention periods.
      </p>

      <H>Security</H>
      <p>
        Data travels over HTTPS. Database access is restricted by row-level security, passwords are
        hashed, sessions can be ended on every device from the account menu, and a password reset
        ends existing sessions.
      </p>

      <H>Your rights</H>
      <p>
        Depending on where you live you may have rights to access, correct, delete or export your
        personal data, and to object to or restrict its processing. Email {email} and we will
        respond within the time the law requires. You may also complain to your data-protection
        authority.
      </p>

      <H>International transfers</H>
      <p>
        Our providers may process data outside your country. Where the law requires it, transfers
        rely on appropriate safeguards such as standard contractual clauses.
      </p>

      <H>Changes</H>
      <p>
        We will post any change here and, for material changes, tell account holders by email
        before it takes effect.
      </p>
    </>
  );
}
