import { ArrowLeft } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, errorMessage } from "@/lib/api";
import { useI18n } from "@/i18n";
import { Button, Field, Input } from "@/components/ui";

export function ForgotPasswordPage() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const response = await api.post<{ message: string; dev_token?: string | null }>(
        "/auth/password-reset",
        { email },
        { skipAuth: true },
      );
      setMessage(response.message);
      setDevToken(response.dev_token ?? null);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <div className="w-full max-w-[400px]">
        <Link to="/login" className="mb-8 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)]">
          <ArrowLeft className="h-3.5 w-3.5" />
          {t("auth.signIn")}
        </Link>
        <h1 className="text-[22px] font-semibold tracking-tight">{t("auth.resetTitle")}</h1>
        <p className="mt-1 text-[12.5px] text-[var(--muted)]">{t("auth.resetBody")}</p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <Field label={t("auth.email")}>
            <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </Field>
          {error ? <p className="text-[12px] text-[var(--danger)]">{error}</p> : null}
          {message ? (
            <div className="rounded-md border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-[12px]">
              {message}
              {devToken ? (
                <div className="mt-2">
                  <p className="text-[11px] text-[var(--muted)]">{t("auth.resetToken")} (development only)</p>
                  <Link
                    to={`/reset-password?token=${encodeURIComponent(devToken)}`}
                    className="mono break-all text-[11px] text-[var(--accent)]"
                  >
                    Open reset link
                  </Link>
                </div>
              ) : null}
            </div>
          ) : null}
          <Button type="submit" variant="primary" className="w-full" loading={loading}>
            {t("auth.sendReset")}
          </Button>
        </form>
      </div>
    </div>
  );
}

export function ResetPasswordPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.post("/auth/password-reset/confirm", { token, new_password: password }, { skipAuth: true });
      setSuccess(true);
      setTimeout(() => navigate("/login"), 1200);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <div className="w-full max-w-[400px]">
        <h1 className="text-[22px] font-semibold tracking-tight">{t("auth.newPassword")}</h1>
        <p className="mt-1 text-[12.5px] text-[var(--muted)]">
          Choose a strong password. All other sessions will be signed out.
        </p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <Field label={t("auth.resetToken")}>
            <Input required value={token} onChange={(event) => setToken(event.target.value)} className="mono text-[11px]" />
          </Field>
          <Field label={t("auth.newPassword")}>
            <Input
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••••"
            />
          </Field>
          {error ? <p className="text-[12px] text-[var(--danger)]">{error}</p> : null}
          {success ? <p className="text-[12px] text-[var(--success)]">{t("auth.resetSuccess")}</p> : null}
          <Button type="submit" variant="primary" className="w-full" loading={loading}>
            {t("auth.confirmReset")}
          </Button>
        </form>
      </div>
    </div>
  );
}
