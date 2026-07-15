"use client";

import { useState } from "react";
import { ChevronDown, Mail, ShieldAlert, UserCheck, Send } from "lucide-react";
import EvidenceCard from "./EvidenceCard";
import AuditTimeline from "./AuditTimeline";
import type { CommunicationDraft, DecisionPayload } from "@/types/workflow";

const RISK_COLOR: Record<string, { fg: string; bg: string }> = {
  LOW: { fg: "var(--color-success)", bg: "var(--color-success-soft)" },
  MEDIUM: { fg: "var(--color-warning)", bg: "var(--color-warning-soft)" },
  HIGH: { fg: "var(--color-alert)", bg: "var(--color-alert-soft)" },
};

function Stat({ label, value, accent }: { label: string; value: string; accent?: { fg: string; bg: string } }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)] px-3.5 py-2.5">
      <span className="text-[10.5px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">{label}</span>
      <span
        className="w-fit rounded px-1.5 py-0.5 text-[13px] font-semibold"
        style={accent ? { color: accent.fg, background: accent.bg } : { color: "var(--color-ink)" }}
      >
        {value}
      </span>
    </div>
  );
}

function Section({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-[var(--color-border)] pt-3">
      <button onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between text-left">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-ink-faint)]">{title}</span>
        <ChevronDown
          className="h-3.5 w-3.5 text-[var(--color-ink-faint)] transition-transform"
          style={{ transform: open ? "rotate(180deg)" : "rotate(0deg)" }}
          strokeWidth={2}
        />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

/** Full preview of a generated (but not-yet-sent) email draft -- subject,
 * recipient, and the reason/body text -- rather than just a one-line
 * summary. This is the primary output for scenarios like an incomplete
 * submission, where no risk/pricing decision was made and the drafted
 * request-for-information email *is* the result of the run. */
function EmailDraftPreview({ draft }: { draft: CommunicationDraft }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-sunken)]">
      <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border)] px-3.5 py-2.5">
        <div className="flex items-start gap-2.5">
          <Mail className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-ink-faint)]" strokeWidth={1.75} />
          <div>
            <p className="text-[12.5px] font-semibold text-[var(--color-ink)]">{draft.subject}</p>
            <p className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-[var(--color-ink-muted)]">
              <UserCheck className="h-3 w-3" strokeWidth={1.75} />
              To: {draft.recipient_role}
            </p>
          </div>
        </div>
        <span className="shrink-0 rounded-full bg-[var(--color-warning-soft)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-warning)]">
          {draft.status.replace(/_/g, " ")}
        </span>
      </div>
      {draft.reason && (
        <p className="px-3.5 py-2.5 text-[12.5px] leading-relaxed text-[var(--color-ink)]">{draft.reason}</p>
      )}
    </div>
  );
}

export default function DecisionCard({ decision, isRunning }: { decision: DecisionPayload | null; isRunning: boolean }) {
  if (!decision) {
    return (
      <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-border-strong)] px-4 py-3 text-center text-[13px] text-[var(--color-ink-faint)]">
        {isRunning ? "Decision summary will appear once the run reaches Phase 8." : "Run a case to see the decision summary."}
      </div>
    );
  }

  const riskAccent = decision.risk_category ? RISK_COLOR[decision.risk_category] ?? RISK_COLOR.MEDIUM : undefined;
  const businessRules = decision.governance_history.length > 0 ? decision.governance_history : decision.recommendation.conditions;
  const humanReviewRequired =
    decision.workflow_metrics.human_reviews > 0 ||
    decision.status.includes("HUMAN") ||
    decision.status.includes("REVIEW") ||
    decision.decision_mode === "HUMAN_REVIEW";

  // A run can stop before risk/pricing ever ran -- e.g. an incomplete
  // submission -- in which case the *result* of the run is the drafted
  // request-for-information email, not a risk decision. Surface that
  // email as the headline rather than showing "—" stats with no context.
  const hasPricingDecision = typeof decision.pricing?.indicative_premium === "number";
  const isAwaitingInfo = decision.recommendation.action === "REQUEST_MORE_INFORMATION" || decision.status.includes("INCOMPLETE");
  const drafts = decision.communication?.drafts ?? [];

  return (
    <div className="rounded-[var(--radius-card)] border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3.5 shadow-[var(--shadow-card)]">
      {/* Stat row */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Risk score" value={decision.risk_score != null ? String(decision.risk_score) : "—"} />
        <Stat label="Risk category" value={decision.risk_category ?? "—"} accent={riskAccent} />
        <Stat
          label="Indicative premium"
          value={decision.pricing.indicative_premium?.toLocaleString() ?? "—"}
        />
        <Stat label="Decision" value={decision.recommendation.action.replace(/_/g, " ")} />
        <Stat
          label="Human review"
          value={humanReviewRequired ? "Required" : "Not required"}
          accent={humanReviewRequired ? RISK_COLOR.HIGH : RISK_COLOR.LOW}
        />
        <Stat label="Emails generated" value={String(decision.communication?.emails_generated ?? 0)} />
      </div>

      {/* Pricing recommendation, or -- when there isn't one -- why the run
          stopped short and what happens next. */}
      <p className="mt-3 text-[12.5px] leading-relaxed text-[var(--color-ink-muted)]">
        {hasPricingDecision ? (
          <>
            <span className="font-semibold text-[var(--color-ink)]">Pricing recommendation:</span> {decision.pricing.recommendation}
          </>
        ) : (
          <>
            <span className="font-semibold text-[var(--color-ink)]">Outcome:</span> {decision.recommendation.reason}
          </>
        )}
      </p>

      {/* Awaiting-information banner: the drafted email(s) requesting the
          missing details, shown up front since it's the actual output of
          this run rather than a risk/pricing decision. */}
      {isAwaitingInfo && drafts.length > 0 && (
        <div className="mt-3 flex flex-col gap-2 rounded-lg border border-[var(--color-warning)]/40 bg-[var(--color-warning-soft)] px-3.5 py-3">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--color-warning)]">
            <Send className="h-3.5 w-3.5" strokeWidth={2} />
            Awaiting more information &mdash; draft email ready
          </p>
          <div className="flex flex-col gap-2">
            {drafts.map((draft) => (
              <EmailDraftPreview key={draft.email_id} draft={draft} />
            ))}
          </div>
        </div>
      )}

      {/* Expandable sections */}
      <div className="mt-3 flex flex-col gap-3">
        <Section title={`Business rules triggered (${businessRules.length})`}>
          {businessRules.length === 0 ? (
            <p className="text-[12.5px] text-[var(--color-ink-faint)]">No governance rules were triggered on this run.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {businessRules.map((rule, i) => (
                <li key={i} className="flex items-start gap-2 text-[12.5px] text-[var(--color-ink)]">
                  <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--color-warning)]" strokeWidth={1.75} />
                  {rule}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title={`Evidence (${decision.decision_evidence.length})`} defaultOpen>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {decision.decision_evidence.map((evidence, i) => (
              <EvidenceCard key={i} index={i + 1} text={evidence} />
            ))}
          </div>
        </Section>

        <Section title={`Audit trail (${decision.audit_trail.length})`}>
          <AuditTimeline steps={decision.audit_trail} />
        </Section>

        <Section title={`Communications (${drafts.length})`} defaultOpen={isAwaitingInfo}>
          {drafts.length === 0 ? (
            <p className="text-[12.5px] text-[var(--color-ink-faint)]">No communications were generated on this run.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {drafts.map((draft) => (
                <EmailDraftPreview key={draft.email_id} draft={draft} />
              ))}
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}
