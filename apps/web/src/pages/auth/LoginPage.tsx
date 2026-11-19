import { ArrowRight, CheckCircle2, FileSearch, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError, errorMessage } from "@/lib/api";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import { Button, Input, Label } from "@/components/ui";

interface OrgChoice {
  organization: string;
  role: string;
}

export function LoginPage() {
  const { t } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationSlug, setOrganizationSlug] = useState("");
  const [organizations, setOrganizations] = useState<OrgChoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email.trim(), password, organizationSlug || undefined);
      navigate(from, { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "organization_required") {
        const details = caught.details as { organizations?: OrgChoice[] } | undefined;
        setOrganizations(details?.organizations ?? []);
        setError("Select the workspace you want to open.");
      } else if (caught instanceof ApiError && caught.code === "account_locked") {
        setError(caught.message);
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="relative hidden overflow-hidden bg-[#0d1f19] p-10 text-[#eef3ef] lg:flex lg:flex-col lg:justify-between">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.16]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.08) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-[#4cc79a] font-display text-[17px] font-bold text-[#062019]">
              R
            </span>
            <div className="leading-tight">
              <div className="font-display text-[15px] font-bold tracking-tight">RESOLVE</div>
              <div className="text-[10px] uppercase tracking-[0.16em] text-[#7f9a8f]">Intelligent exceptions</div>
            </div>
          </div>
        </div>

        <div className="relative max-w-[520px]">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#7fbfa5]">
            Exception management, resolved
          </p>
          <h1 className="font-display text-[40px] font-semibold leading-[1.08] tracking-[-0.03em]">
            Every exception accounted for, from detection to a signed-off resolution.
          </h1>
          <p className="mt-5 max-w-[460px] text-[14px] leading-relaxed text-[#adc3b9]">
            RESOLVE combines deterministic invoice controls with evidence-grounded AI investigation and
            human approval, so operations teams move faster without losing control.
          </p>
          <div className="mt-8 space-y-3.5">
            {[
              { icon: <FileSearch className="h-4 w-4" />, title: "Deterministic first", body: "Rules and Decimal arithmetic decide; AI explains and recommends." },
              { icon: <Sparkles className="h-4 w-4" />, title: "Evidence you can audit", body: "Every AI claim is validated against real documents, pages and records." },
              { icon: <ShieldCheck className="h-4 w-4" />, title: "Human control", body: "High-risk actions require an approval that cannot come from the requester." },
            ].map((item) => (
              <div key={item.title} className="flex gap-3">
                <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[#2a4438] bg-[#132a21] text-[#7fbfa5]">
                  {item.icon}
                </span>
                <div>
                  <p className="text-[13px] font-semibold text-[#e6efea]">{item.title}</p>
                  <p className="text-[12px] text-[#9db5aa]">{item.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="relative flex items-center gap-2 text-[11px] text-[#7f9a8f]">
          <CheckCircle2 className="h-3.5 w-3.5" />
          Multi-tenant · RBAC · immutable audit trail
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-[380px]">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <span className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-[var(--accent)] font-display text-[17px] font-bold text-[var(--on-accent)]">
              R
            </span>
            <span className="font-display text-[17px] font-bold tracking-tight">RESOLVE</span>
          </div>

          <h2 className="text-[24px] font-semibold tracking-tight">{t("auth.welcome")}</h2>
          <p className="mt-1.5 text-[13px] text-[var(--muted)]">{t("auth.subtitle")}</p>

          <form className="mt-7 space-y-4" onSubmit={submit}>
            <div>
              <Label htmlFor="email">{t("auth.email")}</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@company.com"
              />
            </div>
            <div>
              <div className="flex items-center justify-between">
                <Label htmlFor="password">{t("auth.password")}</Label>
                <Link to="/forgot-password" className="mb-1.5 text-[11.5px] font-semibold text-[var(--accent)]">
                  {t("auth.forgot")}
                </Link>
              </div>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••••"
              />
            </div>

            {organizations.length > 0 ? (
              <div>
                <Label htmlFor="org">{t("auth.organization")}</Label>
                <select
                  id="org"
                  className="select"
                  value={organizationSlug}
                  onChange={(event) => setOrganizationSlug(event.target.value)}
                >
                  <option value="">{t("auth.organizationHint")}</option>
                  {organizations.map((choice) => (
                    <option key={choice.organization} value={choice.organization}>
                      {choice.organization} · {choice.role}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            {error ? (
              <div className="rounded-md border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3 py-2 text-[12px] text-[var(--danger)]">
                {error}
              </div>
            ) : null}

            <Button type="submit" variant="primary" size="lg" className="w-full justify-between" loading={loading}>
              <span>{loading ? t("auth.signingIn") : t("auth.signIn")}</span>
              <ArrowRight className="h-4 w-4" />
            </Button>
          </form>

          <p className="mt-6 text-center text-[12px] text-[var(--muted)]">
            Access is by invitation. Contact your administrator if you need an account.
          </p>
        </div>
      </section>
    </div>
  );
}
