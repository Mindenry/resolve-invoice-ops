import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Network, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { formatDateTime, humanize, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
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
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { Integration, WebhookEvent } from "@/types/api";

const KINDS = ["WEBHOOK", "N8N", "REST", "CSV", "EXCEL", "MINIO", "EMAIL"];
const EVENTS = [
  "exception.detected",
  "case.created",
  "case.assigned",
  "case.escalated",
  "case.resolved",
  "approval.requested",
  "approval.decided",
  "resolution.executed",
  "integration.failed",
];

export function IntegrationsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [credentialsFor, setCredentialsFor] = useState<Integration | null>(null);
  const [form, setForm] = useState({ name: "", kind: "WEBHOOK", url: "", events: [] as string[] });
  const [secretKey, setSecretKey] = useState("signing_secret");
  const [secretValue, setSecretValue] = useState("");

  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () => api.get<Integration[]>("/integrations"),
  });

  const events = useQuery({
    queryKey: ["integration-events"],
    queryFn: () => api.get<WebhookEvent[]>("/integrations/events?limit=100"),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post("/integrations", {
        name: form.name,
        kind: form.kind,
        config: { webhook_url: form.url || undefined, base_url: form.url || undefined, test_method: "POST" },
        event_filter: form.events,
        is_enabled: true,
        credentials: {},
      }),
    onSuccess: () => {
      setCreateOpen(false);
      setForm({ name: "", kind: "WEBHOOK", url: "", events: [] });
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Integration created");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const test = useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean; detail: string; status: string }>(`/integrations/${id}/test`, {}),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast[result.ok ? "success" : "error"](result.detail);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const saveCredentials = useMutation({
    mutationFn: () =>
      api.put(`/integrations/${credentialsFor?.id}/credentials`, { credentials: { [secretKey]: secretValue } }),
    onSuccess: () => {
      setCredentialsFor(null);
      setSecretValue("");
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      toast.success("Credentials stored (encrypted)");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const columns: Column<WebhookEvent>[] = [
    { key: "event", header: "Event", render: (row) => <span className="mono text-[11px]">{row.event_type}</span> },
    { key: "direction", header: t("integrations.direction"), render: (row) => <Badge tone={row.direction === "INBOUND" ? "info" : "neutral"}>{humanize(row.direction)}</Badge> },
    { key: "status", header: t("common.status"), render: (row) => <StatusBadge status={row.status} /> },
    { key: "signature", header: t("integrations.signature"), render: (row) => <Badge tone={row.signature_valid ? "success" : "danger"}>{row.signature_valid ? "valid" : "invalid"}</Badge> },
    { key: "response", header: "HTTP", render: (row) => <span className="num">{row.response_status ?? "—"}</span> },
    { key: "attempts", header: t("workflows.attempts"), align: "right", render: (row) => <span className="num">{row.attempts}</span> },
    { key: "error", header: t("common.errorTitle"), render: (row) => <span className="line-clamp-1 max-w-[240px] text-[11px] text-[var(--danger)]">{row.last_error ?? "—"}</span> },
    { key: "created", header: t("common.date"), render: (row) => <span className="text-[11px] text-[var(--muted)]">{formatDateTime(row.created_at)}</span> },
  ];

  return (
    <>
      <PageHeader
        title={t("integrations.title")}
        subtitle={t("integrations.subtitle")}
        actions={
          can("integration:manage") ? (
            <Button size="sm" variant="primary" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              {t("integrations.create")}
            </Button>
          ) : null
        }
      />

      <Tabs defaultValue="registry">
        <TabsList>
          <TabsTrigger value="registry">Registry</TabsTrigger>
          <TabsTrigger value="events">{t("integrations.events")}</TabsTrigger>
        </TabsList>

        <TabsContent value="registry">
          {integrations.isLoading ? (
            <div className="grid gap-3 md:grid-cols-2">{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-36" />)}</div>
          ) : (integrations.data ?? []).length === 0 ? (
            <Card><EmptyState icon={<Network className="h-5 w-5" />} title={t("integrations.noIntegrations")} body="Add a webhook, n8n instance or file import to connect external systems." /></Card>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {(integrations.data ?? []).map((integration) => (
                <Card key={integration.id}>
                  <CardHeader
                    title={
                      <span className="flex items-center gap-2">
                        <Network className="h-4 w-4 text-[var(--muted)]" />
                        {integration.name}
                      </span>
                    }
                    description={`${humanize(integration.kind)} · ${integration.event_filter.length ? integration.event_filter.join(", ") : "all events"}`}
                    actions={<StatusBadge status={integration.status} />}
                  />
                  <CardBody className="space-y-2 pt-3">
                    <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--muted)]">
                      <Badge tone={integration.is_enabled ? "success" : "neutral"}>{integration.is_enabled ? "enabled" : "disabled"}</Badge>
                      <span>{t("integrations.credentials")}: {integration.credential_keys.length || "none"}</span>
                      <span>·</span>
                      <span>{t("integrations.lastChecked")}: {integration.last_checked_at ? timeAgo(integration.last_checked_at) : t("integrations.untested")}</span>
                    </div>
                    {integration.last_error ? (
                      <p className="line-clamp-2 rounded bg-[var(--danger-soft)] px-2 py-1 text-[11px] text-[var(--danger)]">{integration.last_error}</p>
                    ) : null}
                    <div className="flex flex-wrap gap-2">
                      {can("integration:manage") ? (
                        <>
                          <Button size="sm" variant="secondary" loading={test.isPending} onClick={() => test.mutate(integration.id)}>
                            <RefreshCw className="h-3.5 w-3.5" />
                            {t("integrations.test")}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setCredentialsFor(integration)}>
                            <KeyRound className="h-3.5 w-3.5" />
                            {t("integrations.credentials")}
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="events">
          <Card>
            <CardHeader title={t("integrations.events")} description="Signed inbound events and outbound delivery attempts" />
            <DataTable
              columns={columns}
              rows={events.data}
              loading={events.isLoading}
              rowKey={(row) => row.id}
              empty={<EmptyState title="No webhook events" body="Outbound events are recorded here once an integration is subscribed." />}
            />
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent title={t("integrations.create")} description="Secrets are stored separately and encrypted at rest.">
          <div className="space-y-3">
            <Field label={t("common.name")}><Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
            <Field label={t("integrations.kind")}>
              <Select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })}>
                {KINDS.map((kind) => <option key={kind} value={kind}>{humanize(kind)}</option>)}
              </Select>
            </Field>
            <Field label={t("integrations.webhookUrl")} hint={form.kind === "N8N" ? "n8n base URL" : t("common.optional")}>
              <Input value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} placeholder="https://n8n.example.com/webhook/…" />
            </Field>
            <div>
              <p className="label">Event filter</p>
              <div className="flex flex-wrap gap-1.5">
                {EVENTS.map((event) => (
                  <label key={event} className={cn("cursor-pointer rounded border px-1.5 py-0.5 text-[10.5px]", form.events.includes(event) ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-strong)]" : "border-[var(--line)] text-[var(--muted)]")}>
                    <input type="checkbox" className="hidden" checked={form.events.includes(event)} onChange={(e) => setForm({ ...form, events: e.target.checked ? [...form.events, event] : form.events.filter((item) => item !== event) })} />
                    {event}
                  </label>
                ))}
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setCreateOpen(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={create.isPending} disabled={!form.name} onClick={() => create.mutate()}>{t("common.create")}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(credentialsFor)} onOpenChange={(open) => !open && setCredentialsFor(null)}>
        <DialogContent title={`${t("integrations.credentials")} · ${credentialsFor?.name ?? ""}`} description={t("integrations.credentialsHint")}>
          <div className="space-y-3">
            <Field label="Key">
              <Select value={secretKey} onChange={(event) => setSecretKey(event.target.value)}>
                <option value="signing_secret">signing_secret</option>
                <option value="api_key">api_key</option>
                <option value="token">token</option>
              </Select>
            </Field>
            <Field label="Value">
              <Input type="password" value={secretValue} onChange={(event) => setSecretValue(event.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setCredentialsFor(null)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={saveCredentials.isPending} disabled={!secretValue} onClick={() => saveCredentials.mutate()}>Save secret</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
