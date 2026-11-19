import { ArrowLeft, ArrowRight } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, errorMessage } from "@/lib/api";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import { Button, Field, Input } from "@/components/ui";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60);
}

export function RegisterPage() {
  const { t } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [values, setValues] = useState({
    organization_name: "",
    organization_slug: "",
    full_name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const update = (key: keyof typeof values, value: string) =>
    setValues((current) => ({
      ...current,
      [key]: value,
      ...(key === "organization_name" && !current.organization_slug
        ? { organization_slug: slugify(value) }
        : {}),
    }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (values.password.length < 10) {
      setError("Password must be at least 10 characters and contain upper, lower and numeric characters.");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/register", values, { skipAuth: true });
      await login(values.email, values.password);
      navigate("/", { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-5 py-10">
      <div className="w-full max-w-[440px]">
        <Link to="/login" className="mb-8 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)]">
          <ArrowLeft className="h-3.5 w-3.5" />
          {t("auth.signIn")}
        </Link>
        <div className="mb-6 flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-[9px] bg-[var(--accent)] font-display text-[17px] font-bold text-[var(--on-accent)]">
            R
          </span>
          <span className="font-display text-[16px] font-bold tracking-tight">RESOLVE</span>
        </div>
        <h1 className="text-[22px] font-semibold tracking-tight">{t("auth.register")}</h1>
        <p className="mt-1 text-[12.5px] text-[var(--muted)]">{t("auth.registerSubtitle")}</p>

        <form className="mt-6 space-y-4" onSubmit={submit}>
          <Field label={t("auth.orgName")}>
            <Input
              required
              value={values.organization_name}
              onChange={(event) => update("organization_name", event.target.value)}
              placeholder="Northwind Operations"
            />
          </Field>
          <Field label={t("auth.orgSlug")} hint="a-z, 0-9, dash">
            <Input
              required
              pattern="[a-z0-9][a-z0-9-]*"
              value={values.organization_slug}
              onChange={(event) => update("organization_slug", slugify(event.target.value))}
              placeholder="northwind"
            />
          </Field>
          <Field label={t("auth.fullName")}>
            <Input
              required
              value={values.full_name}
              onChange={(event) => update("full_name", event.target.value)}
              placeholder="Narin Chai"
            />
          </Field>
          <Field label={t("auth.email")}>
            <Input
              required
              type="email"
              value={values.email}
              onChange={(event) => update("email", event.target.value)}
              placeholder="you@company.com"
            />
          </Field>
          <Field label={t("auth.password")} hint="10+ chars, upper, lower, digit">
            <Input
              required
              type="password"
              value={values.password}
              onChange={(event) => update("password", event.target.value)}
              placeholder="••••••••••"
            />
          </Field>
          {error ? (
            <div className="rounded-md border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3 py-2 text-[12px] text-[var(--danger)]">
              {error}
            </div>
          ) : null}
          <Button type="submit" variant="primary" size="lg" className="w-full justify-between" loading={loading}>
            {t("auth.createAccount")}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}
