import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Moon, ShieldCheck, Sun, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { formatDate, humanize } from "@/lib/format";
import { ROLE_LABELS, useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import { useTheme } from "@/providers/theme";
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Dialog,
  DialogContent,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import type { ExceptionRule, Member, Page } from "@/types/api";

const ROLES = ["org_admin", "ops_manager", "investigator", "approver", "viewer"];

export function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const { session, can, refresh } = useAuth();
  const { theme, setTheme } = useTheme();
  const queryClient = useQueryClient();

  const [org, setOrg] = useState({ name: "", legal_name: "", tax_id: "", default_currency: "USD", timezone: "UTC" });
  const [policy, setPolicy] = useState({ approval_required_risk: "HIGH", allow_self_approval: false, require_purchase_order: true });
  const [inviteOpen, setInviteOpen] = useState(false);
  const [invite, setInvite] = useState({ email: "", full_name: "", role: "investigator", temporary_password: "" });
  const [ruleConfig, setRuleConfig] = useState<ExceptionRule | null>(null);
  const [ruleJson, setRuleJson] = useState("{}");

  const organization = session?.organization;

  useEffect(() => {
    if (organization) {
      setOrg({
        name: organization.name,
        legal_name: organization.legal_name ?? "",
        tax_id: organization.tax_id ?? "",
        default_currency: organization.default_currency,
        timezone: organization.timezone,
      });
      const settings = organization.settings ?? {};
      const approval = settings.approval_policy ?? {};
      setPolicy({
        approval_required_risk: String(approval.approval_required_risk ?? "HIGH"),
        allow_self_approval: Boolean(approval.allow_self_approval),
        require_purchase_order: Boolean(settings.require_purchase_order ?? true),
      });
    }
  }, [organization]);

  const members = useQuery({
    queryKey: ["members"],
    queryFn: () => api.get<Page<Member>>("/users?page_size=100"),
  });

  const matrix = useQuery({
    queryKey: ["roles", "matrix"],
    queryFn: () => api.get<{ roles: { id: string; code: string; name: string; rank: number }[]; permissions: { id: string; code: string; description: string; group: string }[]; matrix: Record<string, string[]> }>("/organizations/roles/matrix"),
  });

  const ai = useQuery({
    queryKey: ["organizations", "ai"],
    queryFn: () => api.get<{ settings: Record<string, any> }>("/organizations/ai-configuration"),
    enabled: can("ai:configure"),
  });

  const preferences = useQuery({
    queryKey: ["notifications", "preferences"],
    queryFn: () => api.get<{ event_type: string; label: string; in_app: boolean; email: boolean }[]>("/notifications/preferences"),
  });

  const rules = useQuery({
    queryKey: ["exceptions", "rules"],
    queryFn: () => api.get<ExceptionRule[]>("/exceptions/rules"),
  });

  const orgSettings = useQuery({
    queryKey: ["organizations", "settings"],
    queryFn: () => api.get<{ settings: Record<string, any>; branding: Record<string, any> }>("/organizations/settings"),
  });

  useEffect(() => {
    if (orgSettings.data?.settings) {
      const settings = orgSettings.data.settings;
      const approval = settings.approval_policy ?? {};
      setPolicy({
        approval_required_risk: String(approval.approval_required_risk ?? "HIGH"),
        allow_self_approval: Boolean(approval.allow_self_approval),
        require_purchase_order: Boolean(settings.require_purchase_order ?? true),
      });
    }
  }, [orgSettings.data]);

  const saveOrg = useMutation({
    mutationFn: () => api.patch("/organizations/current", org),
    onSuccess: async () => { await refresh(); toast.success(t("settings.saved")); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const savePolicy = useMutation({
    mutationFn: () =>
      api.put("/organizations/settings", {
        settings: {
          approval_policy: {
            approval_required_risk: policy.approval_required_risk,
            allow_self_approval: policy.allow_self_approval,
          },
          require_purchase_order: policy.require_purchase_order,
        },
      }),
    onSuccess: async () => { await refresh(); toast.success(t("settings.saved")); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const inviteMember = useMutation({
    mutationFn: () =>
      api.post("/users", {
        email: invite.email,
        full_name: invite.full_name,
        role: invite.role,
        job_title: null,
        temporary_password: invite.temporary_password || null,
      }),
    onSuccess: () => {
      setInviteOpen(false);
      setInvite({ email: "", full_name: "", role: "investigator", temporary_password: "" });
      void queryClient.invalidateQueries({ queryKey: ["members"] });
      toast.success("Member invited");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const updateMember = useMutation({
    mutationFn: ({ membershipId, payload }: { membershipId: string; payload: Record<string, unknown> }) =>
      api.patch(`/users/${membershipId}`, payload),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["members"] }); toast.success(t("settings.roleChanged")); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const updatePreference = useMutation({
    mutationFn: (payload: { event_type: string; in_app: boolean; email: boolean }) => api.put("/notifications/preferences", payload),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["notifications", "preferences"] }); toast.success("Preference saved"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const toggleRule = useMutation({
    mutationFn: ({ code, enabled }: { code: string; enabled: boolean }) => api.patch(`/exceptions/rules/${code}`, { is_enabled: enabled }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["exceptions", "rules"] }); toast.success("Rule updated"); },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const saveRule = useMutation({
    mutationFn: () => {
      let config: Record<string, unknown>;
      try { config = JSON.parse(ruleJson); } catch { throw new Error("Configuration must be valid JSON"); }
      return api.patch(`/exceptions/rules/${ruleConfig?.code}`, { config, change_note: "Updated from settings" });
    },
    onSuccess: () => {
      setRuleConfig(null);
      void queryClient.invalidateQueries({ queryKey: ["exceptions", "rules"] });
      toast.success("New rule version created");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!session) return null;

  return (
    <>
      <PageHeader title={t("settings.title")} subtitle={t("settings.subtitle")} />

      <Tabs defaultValue="organization">
        <TabsList>
          <TabsTrigger value="organization">{t("settings.organization")}</TabsTrigger>
          <TabsTrigger value="policy">{t("settings.policy")}</TabsTrigger>
          <TabsTrigger value="members">{t("settings.members")}</TabsTrigger>
          <TabsTrigger value="roles">{t("settings.roles")}</TabsTrigger>
          <TabsTrigger value="rules">{t("settings.rules")}</TabsTrigger>
          <TabsTrigger value="notifications">{t("settings.notifications")}</TabsTrigger>
          <TabsTrigger value="ai">{t("settings.ai")}</TabsTrigger>
          <TabsTrigger value="appearance">{t("settings.appearance")}</TabsTrigger>
        </TabsList>

        <TabsContent value="organization">
          <Card>
            <CardHeader title={t("settings.organization")} description="Legal identity and regional defaults" />
            <CardBody className="grid gap-3 sm:grid-cols-2">
              <Field label={t("common.name")}><Input value={org.name} onChange={(event) => setOrg({ ...org, name: event.target.value })} disabled={!can("org:update")} /></Field>
              <Field label={t("common.organization")}><Input value={org.legal_name} onChange={(event) => setOrg({ ...org, legal_name: event.target.value })} disabled={!can("org:update")} /></Field>
              <Field label="Tax ID"><Input value={org.tax_id} onChange={(event) => setOrg({ ...org, tax_id: event.target.value })} disabled={!can("org:update")} /></Field>
              <Field label={t("common.currency")}><Input maxLength={3} value={org.default_currency} onChange={(event) => setOrg({ ...org, default_currency: event.target.value.toUpperCase() })} disabled={!can("org:update")} /></Field>
              <Field label="Timezone"><Input value={org.timezone} onChange={(event) => setOrg({ ...org, timezone: event.target.value })} disabled={!can("org:update")} /></Field>
              <div className="flex items-end justify-end">
                <Button variant="primary" loading={saveOrg.isPending} disabled={!can("org:update")} onClick={() => saveOrg.mutate()}>{t("common.save")}</Button>
              </div>
              <div className="sm:col-span-2 rounded border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] text-[var(--muted)]">
                Slug: <span className="mono text-[var(--ink)]">{organization?.slug}</span> · Created {organization?.created_at ? formatDate(organization.created_at) : "—"} · {organization?.is_demo ? "Demo workspace" : "Production workspace"}
              </div>
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="policy">
          <Card>
            <CardHeader title={t("settings.policy")} description="Deterministic approval and purchase order rules" />
            <CardBody className="max-w-2xl space-y-4">
              <Field label={t("settings.approvalThreshold")}>
                <Select value={policy.approval_required_risk} onChange={(event) => setPolicy({ ...policy, approval_required_risk: event.target.value })} disabled={!can("org:update")}>
                  {["MEDIUM", "HIGH", "CRITICAL"].map((value) => <option key={value} value={value}>{humanize(value)} and above</option>)}
                </Select>
              </Field>
              <label className="flex items-start gap-2 text-[12.5px]">
                <input type="checkbox" className="mt-0.5" checked={policy.allow_self_approval} onChange={(event) => setPolicy({ ...policy, allow_self_approval: event.target.checked })} disabled={!can("org:update")} />
                <span>{t("settings.allowSelfApproval")}<span className="block text-[11px] text-[var(--muted)]">Not recommended. High-risk financial actions still require a second person.</span></span>
              </label>
              <label className="flex items-start gap-2 text-[12.5px]">
                <input type="checkbox" className="mt-0.5" checked={policy.require_purchase_order} onChange={(event) => setPolicy({ ...policy, require_purchase_order: event.target.checked })} disabled={!can("org:update")} />
                <span>{t("settings.requirePo")}<span className="block text-[11px] text-[var(--muted)]">Invoices without a PO raise a HIGH severity exception.</span></span>
              </label>
              <Button variant="primary" loading={savePolicy.isPending} disabled={!can("org:update")} onClick={() => savePolicy.mutate()}>{t("common.save")}</Button>
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="members">
          <Card>
            <CardHeader
              title={t("settings.members")}
              description="Role assignments are enforced by the backend on every request."
              actions={can("user:manage") ? <Button size="sm" variant="primary" onClick={() => setInviteOpen(true)}><UserPlus className="h-3.5 w-3.5" />{t("settings.invite")}</Button> : null}
            />
            {members.isLoading ? <div className="p-4"><Skeleton className="h-24" /></div> : (
              <div className="overflow-x-auto">
                <table className="table">
                  <thead><tr><th>{t("common.member")}</th><th>{t("common.role")}</th><th>{t("common.status")}</th><th>{t("common.created")}</th><th /></tr></thead>
                  <tbody>
                    {(members.data?.items ?? []).map((member) => (
                      <tr key={member.id}>
                        <td>
                          <div className="flex items-center gap-2">
                            <Avatar name={member.full_name} size={24} />
                            <div><div className="text-[12.5px] font-semibold">{member.full_name}</div><div className="text-[10.5px] text-[var(--muted)]">{member.email}</div></div>
                          </div>
                        </td>
                        <td>
                          {can("user:manage") ? (
                            <Select
                              className="h-7 w-auto py-0 text-[11.5px]"
                              value={member.role_code}
                              onChange={(event) => updateMember.mutate({ membershipId: member.id, payload: { role: event.target.value } })}
                            >
                              {ROLES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
                            </Select>
                          ) : (
                            <Badge tone="neutral">{ROLE_LABELS[member.role_code]}</Badge>
                          )}
                        </td>
                        <td><Badge tone={member.is_active ? "success" : "neutral"}>{member.is_active ? "active" : "inactive"}</Badge></td>
                        <td className="text-[11px] text-[var(--muted)]">{member.created_at ? formatDate(member.created_at) : "—"}</td>
                        <td className="text-right">
                          {can("user:manage") ? (
                            <Button size="sm" variant="ghost" onClick={() => updateMember.mutate({ membershipId: member.id, payload: { is_active: !member.is_active } })}>
                              {member.is_active ? t("settings.deactivate") : t("settings.activate")}
                            </Button>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </TabsContent>

        <TabsContent value="roles">
          <Card>
            <CardHeader title={t("settings.roles")} description="Backend permission matrix (read-only)" />
            <CardBody className="overflow-x-auto">
              {matrix.isLoading ? <Skeleton className="h-40" /> : (
                <table className="table">
                  <thead><tr><th>Permission</th>{matrix.data?.roles.map((role) => <th key={role.code} className="text-center">{role.name}</th>)}</tr></thead>
                  <tbody>
                    {matrix.data?.permissions.map((permission) => (
                      <tr key={permission.id}>
                        <td><span className="mono text-[10.5px]">{permission.code}</span><div className="text-[10.5px] text-[var(--muted)]">{permission.description}</div></td>
                        {matrix.data?.roles.map((role) => (
                          <td key={role.code} className="text-center">
                            {matrix.data?.matrix[role.code]?.includes(permission.code) ? <Check className="mx-auto h-3.5 w-3.5 text-[var(--success)]" /> : <span className="text-[var(--line-strong)]">—</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="rules">
          <Card>
            <CardHeader title={t("settings.rules")} description="Versioned deterministic rules. Saving configuration creates a new version." />
            <CardBody className="space-y-2">
              {rules.isLoading ? <Skeleton className="h-40" /> : (rules.data ?? []).map((rule) => (
                <div key={rule.id} className="flex flex-wrap items-center gap-3 rounded border border-[var(--line)] px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="mono text-[11px] font-semibold">{rule.code}</span>
                      <Badge tone="neutral">v{rule.active_version ?? 1}</Badge>
                      <Badge tone="neutral">{humanize(rule.exception_type)}</Badge>
                    </div>
                    <p className="text-[12px]">{rule.name}</p>
                  </div>
                  <label className="flex items-center gap-1.5 text-[11.5px]">
                    <input type="checkbox" checked={rule.is_enabled} disabled={!can("org:update")} onChange={(event) => toggleRule.mutate({ code: rule.code, enabled: event.target.checked })} />
                    {rule.is_enabled ? t("exceptions.ruleEnabled") : t("exceptions.ruleDisabled")}
                  </label>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={!can("org:update")}
                    onClick={() => { setRuleConfig(rule); setRuleJson(JSON.stringify(rule.config, null, 2)); }}
                  >
                    {t("common.edit")}
                  </Button>
                </div>
              ))}
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="notifications">
          <Card>
            <CardHeader title={t("settings.notifications")} description="Your delivery preferences per event" />
            <CardBody>
              {preferences.isLoading ? <Skeleton className="h-40" /> : (
                <table className="table">
                  <thead><tr><th>Event</th><th className="text-center">{t("settings.notificationInApp")}</th><th className="text-center">{t("settings.notificationEmail")}</th></tr></thead>
                  <tbody>
                    {(preferences.data ?? []).map((preference) => (
                      <tr key={preference.event_type}>
                        <td>{preference.label}</td>
                        {(["in_app", "email"] as const).map((channel) => (
                          <td key={channel} className="text-center">
                            <input
                              type="checkbox"
                              checked={preference[channel]}
                              onChange={(event) =>
                                updatePreference.mutate({
                                  event_type: preference.event_type,
                                  in_app: channel === "in_app" ? event.target.checked : preference.in_app,
                                  email: channel === "email" ? event.target.checked : preference.email,
                                })
                              }
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="ai">
          <Card>
            <CardHeader title={t("settings.ai")} description={t("settings.aiManaged")} />
            <CardBody className="max-w-2xl space-y-3">
              {!can("ai:configure") ? <EmptyState title="Restricted" body="Organization admins can view AI configuration." /> : ai.isLoading ? <Skeleton className="h-32" /> : (
                <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded border border-[var(--line)] px-3 py-2"><p className="eyebrow">LLM provider</p><p className="mt-1 text-[13px] font-semibold">{String(ai.data?.settings.provider ?? "—")}</p><p className="text-[11px] text-[var(--muted)]">{String(ai.data?.settings.model ?? "")}</p></div>
                    <div className="rounded border border-[var(--line)] px-3 py-2"><p className="eyebrow">Embeddings</p><p className="mt-1 text-[13px] font-semibold">{String(ai.data?.settings.embedding_provider ?? "—")}</p><p className="text-[11px] text-[var(--muted)]">{String(ai.data?.settings.embedding_model ?? "")}</p></div>
                    <div className="rounded border border-[var(--line)] px-3 py-2"><p className="eyebrow">Configured</p><div className="mt-1"><Badge tone={ai.data?.settings.configured ? "success" : "warning"}>{ai.data?.settings.configured ? "yes" : "no"}</Badge></div></div>
                    <div className="rounded border border-[var(--line)] px-3 py-2"><p className="eyebrow">Deterministic stub</p><div className="mt-1"><Badge tone={ai.data?.settings.deterministic_stub ? "warning" : "success"}>{ai.data?.settings.deterministic_stub ? "active (testing only)" : "no"}</Badge></div></div>
                  </div>
                  <p className="rounded border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] text-[var(--muted)]">
                    Providers, API keys and model names are configured in the API environment (<span className="mono">AI_PROVIDER</span>, <span className="mono">AI_MODEL</span>, <span className="mono">AI_API_KEY</span>). Secrets are never exposed to the browser. Every AI result records provider, model, prompt version, tokens and cost.
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </TabsContent>

        <TabsContent value="appearance">
          <Card>
            <CardHeader title={t("settings.appearance")} />
            <CardBody className="max-w-xl space-y-4">
              <div>
                <p className="label">{t("common.theme")}</p>
                <div className="flex gap-2">
                  <Button variant={theme === "light" ? "primary" : "secondary"} size="sm" onClick={() => setTheme("light")}><Sun className="h-3.5 w-3.5" />{t("common.light")}</Button>
                  <Button variant={theme === "dark" ? "primary" : "secondary"} size="sm" onClick={() => setTheme("dark")}><Moon className="h-3.5 w-3.5" />{t("common.dark")}</Button>
                </div>
              </div>
              <div>
                <p className="label">{t("common.language")}</p>
                <div className="flex gap-2">
                  <Button variant={locale === "en" ? "primary" : "secondary"} size="sm" onClick={() => setLocale("en")}>English</Button>
                  <Button variant={locale === "th" ? "primary" : "secondary"} size="sm" onClick={() => setLocale("th")}>ไทย</Button>
                </div>
              </div>
              <div className="rounded border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] text-[var(--muted)]">
                <ShieldCheck className="mr-1 inline h-3.5 w-3.5" />
                Demo data is generated through the seed script and is clearly labelled. AI features require a configured provider; the deterministic stub is never enabled in production.
              </div>
            </CardBody>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent title={t("settings.invite")} description="If no temporary password is set, the member receives a reset link through the configured email backend.">
          <div className="space-y-3">
            <Field label={t("common.email")}><Input type="email" value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} /></Field>
            <Field label={t("auth.fullName")}><Input value={invite.full_name} onChange={(event) => setInvite({ ...invite, full_name: event.target.value })} /></Field>
            <Field label={t("common.role")}>
              <Select value={invite.role} onChange={(event) => setInvite({ ...invite, role: event.target.value })}>
                {ROLES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}
              </Select>
            </Field>
            <Field label="Temporary password" hint={t("common.optional")}>
              <Input type="password" value={invite.temporary_password} onChange={(event) => setInvite({ ...invite, temporary_password: event.target.value })} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setInviteOpen(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={inviteMember.isPending} disabled={!invite.email || !invite.full_name} onClick={() => inviteMember.mutate()}>{t("common.create")}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(ruleConfig)} onOpenChange={(open) => !open && setRuleConfig(null)}>
        <DialogContent title={`${ruleConfig?.code ?? ""} · configuration`} description="Saving creates a new immutable rule version and an audit entry." wide>
          <div className="space-y-3">
            <Textarea className="mono text-[11px]" rows={12} value={ruleJson} onChange={(event) => setRuleJson(event.target.value)} />
            <p className="text-[11px] text-[var(--muted)]">Test cases: {ruleConfig?.test_cases.length ?? 0} · Conditions: {JSON.stringify(ruleConfig?.conditions ?? {})}</p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setRuleConfig(null)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={saveRule.isPending} onClick={() => saveRule.mutate()}>{t("exceptions.saveConfig")}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
