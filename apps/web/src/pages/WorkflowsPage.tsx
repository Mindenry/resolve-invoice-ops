import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, RefreshCw, Workflow } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";

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
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { BackgroundJob, WorkflowExecution } from "@/types/api";
export function WorkflowsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [triggerKey, setTriggerKey] = useState<string | null>(null);
  const [payload, setPayload] = useState("{}");
  const [caseId, setCaseId] = useState("");
  const templates = useQuery({
    queryKey: ["workflows", "templates"],
    queryFn: () => api.get<{ key: string; name: string; description: string; trigger_event: string; file_name: string; required_parameters: string[] }[]>("/workflows/templates"),
  });
  const executions = useQuery({
    queryKey: ["workflows", "executions"],
    queryFn: () => api.get<WorkflowExecution[]>("/workflows/executions?limit=100"),
  });
  const jobs = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<BackgroundJob[]>("/jobs?limit=100"),
    refetchInterval: 15_000,
  });
  const trigger = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>;
      try { parsed = JSON.parse(payload || "{}"); } catch { throw new Error("Payload must be valid JSON"); }
      return api.post<WorkflowExecution>(`/workflows/${triggerKey}/trigger`, { case_id: caseId || null, payload: parsed });
    },
    onSuccess: (result) => {
      setTriggerKey(null);
      setPayload("{}");
      setCaseId("");
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      if (result.status === "FAILED") toast.error(result.error ?? "Workflow failed");
      else toast.success("Workflow triggered");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.post(`/workflows/executions/${id}/retry`, {}),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["workflows"] }); toast.success("Retry started"); },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const retryJob = useMutation({
    mutationFn: (id: string) => api.post(`/jobs/${id}/retry`, {}),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["jobs"] }); toast.success("Job queued"); },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const executionColumns: Column<WorkflowExecution>[] = [
    {
      key: "workflow",
      header: t("workflows.key"),
      render: (row) => (
        <div>
          <div className="mono text-[11.5px] font-semibold">{row.workflow_key}</div>
          <div className="text-[10.5px] text-[var(--muted)]">{row.trigger_type}{row.case_id ? ` · case ${row.case_id.slice(0, 8)}` : ""}</div>
        </div>
      ),
    },
    { key: "status", header: t("common.status"), render: (row) => <StatusBadge status={row.status} /> },
    { key: "attempts", header: t("workflows.attempts"), align: "right", render: (row) => <span className="num">{row.attempts}</span> },
    { key: "error", header: t("common.errorTitle"), render: (row) => <span className="line-clamp-2 max-w-[320px] text-[11px] text-[var(--danger)]">{row.error ?? "—"}</span> },
    { key: "started", header: t("common.date"), render: (row) => <span className="text-[11px] text-[var(--muted)]">{row.started_at ? formatDateTime(row.started_at) : formatDateTime(row.created_at)}</span> },
    {
      key: "actions",
      header: "",
      render: (row) =>
        row.status === "FAILED" && can("workflow:run") ? (
          <Button size="sm" variant="secondary" loading={retry.isPending} onClick={() => retry.mutate(row.id)}>
            <RefreshCw className="h-3.5 w-3.5" />
            {t("common.retry")}
          </Button>
        ) : null,
    },
  ];
  const jobColumns: Column<BackgroundJob>[] = [
    { key: "task", header: t("workflows.task"), render: (row) => <span className="mono text-[11px]">{row.task_name}</span> },
    { key: "status", header: t("common.status"), render: (row) => <StatusBadge status={row.status} /> },
    { key: "attempts", header: t("workflows.attempts"), align: "right", render: (row) => <span className="num">{row.attempts}/{row.max_attempts}</span> },
    { key: "error", header: t("common.errorTitle"), render: (row) => <span className="line-clamp-2 max-w-[360px] text-[11px] text-[var(--danger)]">{row.error ?? "—"}</span> },
    { key: "created", header: t("common.created"), render: (row) => <span className="text-[11px] text-[var(--muted)]">{timeAgo(row.created_at)}</span> },
    {
      key: "actions",
      header: "",
      render: (row) =>
        ["FAILED", "RETRYING"].includes(row.status) && can("workflow:run") ? (
          <Button size="sm" variant="secondary" loading={retryJob.isPending} onClick={() => retryJob.mutate(row.id)}>
            {t("common.retry")}
          </Button>
        ) : null,
    },
  ];
  return (
    <>
      <PageHeader title={t("workflows.title")} subtitle={t("workflows.subtitle")} />
      <Tabs defaultValue="templates">
        <TabsList>
          <TabsTrigger value="templates">{t("workflows.templates")}</TabsTrigger>
          <TabsTrigger value="executions">{t("workflows.executions")}</TabsTrigger>
          <TabsTrigger value="jobs">{t("workflows.jobs")}</TabsTrigger>
        </TabsList>
        <TabsContent value="templates">
          {templates.isLoading ? (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} className="h-32" />)}</div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {(templates.data ?? []).map((template) => (
                <Card key={template.key}>
                  <CardBody className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--accent-soft)] text-[var(--accent)]">
                        <Workflow className="h-4 w-4" />
                      </span>
                      <Badge tone="neutral">{template.trigger_event}</Badge>
                    </div>
                    <p className="text-[13px] font-semibold">{template.name}</p>
                    <p className="text-[11.5px] leading-snug text-[var(--muted)]">{template.description}</p>
                    <p className="mono text-[9.5px] text-[var(--muted)]">{template.file_name}</p>
                    {can("workflow:run") ? (
                      <Button size="sm" variant="secondary" onClick={() => setTriggerKey(template.key)}>
                        <Play className="h-3.5 w-3.5" />
                        {t("workflows.trigger")}
                      </Button>
                    ) : null}
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="executions">
          <Card>
            <DataTable
              columns={executionColumns}
              rows={executions.data}
              loading={executions.isLoading}
              rowKey={(row) => row.id}
              empty={<EmptyState title="No workflow executions" body="Executions and their failures appear here. Nothing is marked successful unless the call succeeded." />}
            />
          </Card>
        </TabsContent>
        <TabsContent value="jobs">
          <Card>
            <CardHeader title={t("workflows.jobs")} description="Document processing, investigations, notifications and evaluations" />
            <DataTable
              columns={jobColumns}
              rows={jobs.data}
              loading={jobs.isLoading}
              rowKey={(row) => row.id}
              empty={<EmptyState title="No background jobs" />}
            />
          </Card>
        </TabsContent>
      </Tabs>
      <Dialog open={Boolean(triggerKey)} onOpenChange={(open) => !open && setTriggerKey(null)}>
        <DialogContent title={t("workflows.trigger")} description="Requires an enabled n8n integration. Without one the execution is recorded as failed.">
          <div className="space-y-3">
            <Field label={t("workflows.key")}><Input value={triggerKey ?? ""} readOnly /></Field>
            <Field label={t("common.case")} hint="UUID, optional"><Input value={caseId} onChange={(event) => setCaseId(event.target.value)} /></Field>
            <Field label="Payload (JSON)"><Textarea rows={5} className="mono text-[11px]" value={payload} onChange={(event) => setPayload(event.target.value)} /></Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setTriggerKey(null)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={trigger.isPending} onClick={() => trigger.mutate()}>{t("workflows.trigger")}</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
