import type { Metadata } from "next";
import { company, display } from "@/lib/company";

export const metadata: Metadata = { title: "Refund Policy" };

export default function RefundsPage() {
  const email = display(company.email, "billing contact email");
  return (
    <>
      <h1 className="text-2xl font-semibold text-content">Refund &amp; Cancellation Policy</h1>
      <p>
        <strong className="text-content">Cancelling.</strong> You can cancel a paid plan at any
        time. It stays active until the end of the period you have paid for, then returns to the
        free plan. Your reports are not deleted when you downgrade.
      </p>
      <p>
        <strong className="text-content">Refunds.</strong> If you are not satisfied, ask for a
        refund within {company.refundDays} days of a payment and we will refund that payment in
        full if fewer than half of that period&apos;s included analyses were used. After that,
        payments are non-refundable except where the law requires otherwise.
      </p>
      <p>
        <strong className="text-content">Failed analyses</strong> are never counted against your
        plan, so there is nothing to refund for them.
      </p>
      <p>
        <strong className="text-content">How.</strong> Email {email} from your account&apos;s email
        address. Approved refunds go back to the original payment method, normally within 5–10
        business days depending on your bank.
      </p>
    </>
  );
}
