/**
 * The operator's business details, for the legal and contact pages.
 *
 * Set at build time in the frontend host's environment variables (Netlify,
 * Render or Cloudflare Pages), then redeploy: they are baked into the pages.
 * Until the name and contact email are set, every legal page shows a banner
 * saying it is an unfinished template, so placeholder text can never be read
 * as the operator's actual policy.
 */
export const company = {
  name: process.env.NEXT_PUBLIC_COMPANY_NAME || "",
  email: process.env.NEXT_PUBLIC_CONTACT_EMAIL || "",
  address: process.env.NEXT_PUBLIC_COMPANY_ADDRESS || "",
  jurisdiction: process.env.NEXT_PUBLIC_GOVERNING_LAW || "",
  refundDays: Number(process.env.NEXT_PUBLIC_REFUND_WINDOW_DAYS || "14") || 14,
  effectiveDate: process.env.NEXT_PUBLIC_LEGAL_EFFECTIVE_DATE || "",
  // Named in the privacy policy's sub-processor list, e.g. "Netlify".
  websiteHost: process.env.NEXT_PUBLIC_WEBSITE_HOST || "",
};

export const companyConfigured = Boolean(company.name && company.email);

export function display(value: string, placeholder: string): string {
  return value || `[${placeholder}]`;
}
