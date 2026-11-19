import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  FileText,
  GitMerge,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
  UserPlus,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api";
import { confidence, formatDate, formatDateTime, formatNumber, humanize, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Avatar,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  Field,
  Input,
  PriorityBadge,
  RiskBadge,
  Select,
  SeverityBadge,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import type { Approval, CaseDetail, Investigation, Resolution } from "@/types/api";

const ACTION_TEMPLATES: Record<string, Record<string, unknown>> = {
  UPDATE_CASE_PRIORITY: { priority: "HIGH" },
  ASSIGN_CASE: { user_id: "" },
  ESCALATE_CASE: { reason: "SLA at risk", priority: "URGENT" },
  REQUEST_VENDOR_CONFIRMATION: { vendor_id: "", message: "Please confirm the invoice details." },
  REQUEST_MISSING_DOCUMENTS: { vendor_id: "", requested_items: ["Purchase order"] },
  NOTIFY_TEAM: { message: "Case requires attention." },
  CREATE_EMAIL_DRAFT: { to: "ap@example.com", subject: "Invoice query", body: "Please review the attached invoice." },
  MARK_DUPLICATE: { invoice_id: "", duplicate_invoice_id: "", note: "Confirmed duplicate" },
  RETRY_INTEGRATION: { integration_id: "" },
  RETRY_BACKGROUND_JOB: { job_id: "" },
  CREATE_APPROVAL_REQUEST: {},
};

export function CaseDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveSummary, setResolveSummary] = useState("");
  const [closeAfter, setCloseAfter] = useState(true);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignUser, setAssignUser] = useState("");
  const [escalateOpen, setEscalateOpen] = useState(false);
  const [escalateReason, setEscalateReason] = useState("");
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSource, setMergeSource] = useState("");
  const [comment, setComment] = useState("");
  const [commentVisibility, setCommentVisibility] = useState<"INTERNAL" | "EXTERNAL">("INTERNAL");
  const [proposeOpen, setProposeOpen] = useState(false);
  const [actionType, setActionType] = useState("ESCALATE_CASE");
  const [actionDescription, setActionDescription] = useState("");
  const [actionParams, setActionParams] = useState(JSON.stringify(ACTION_TEMPLATES.ESCALATE_CASE, null, 2));
  const [requestApproval, setRequestApproval] = useState(true);
  const [executeId, setExecuteId] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["case", id],
    queryFn: () => api.get<CaseDetail>(`/cases/${id}`),
    refetchInterval: (query) => (query.state.data?.status === "AWAITING_APPROVAL" ? 20_000 : false),
  });

  const investigations = useQuery({
    queryKey: ["case", id, "investigations"],
    queryFn: () => api.get<Investigation[]>(`/cases/${id}/investigations`),
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.status === "QUEUED" || item.status === "RUNNING") ? 3_000 : false,
  });

  const resolutions = useQuery({
    queryKey: ["case", id, "resolutions"],
    queryFn: () => api.get<Resolution[]>(`/cases/${id}/resolutions`),
  });

  const approvals = useQuery({
    queryKey: ["approvals", "for-case", id],
    queryFn: () => api.get<{ items: Approval[] }>("/approvals?page_size=100"),
    select: (data) => data.items.filter((item) => item.case_id === id),
  });

  const aiStatus = useQuery({
    queryKey: ["ai", "status"],
    queryFn: () =>
      api.get<{ configured: boolean; available: boolean; provider: string; model?: string; deterministic_stub: boolean; detail: string }>(
        "/investigations/ai-status",
      ),
    staleTime: 60_000,
  });

  const members = useQuery({
    queryKey: ["members", "assignable"],
    queryFn: () => api.get<{ id: string; full_name: string; email: string; role: string }[]>("/organizations/members/assignable"),
    enabled: assignOpen,
  });

  const actionCatalog = useQuery({
    queryKey: ["resolutions", "actions"],
    queryFn: () => api.get<{ action_type: string; label: string; description: string; default_risk: string; requires_approval?: boolean; parameters_schema: Record<string, any> }[]>("/resolutions/actions"),
    enabled: proposeOpen,
  });

  const invalidateCase = () => {
    void queryClient.invalidateQueries({ queryKey: ["case", id] });
    void queryClient.invalidateQueries({ queryKey: ["cases"] });
    void queryClient.invalidateQueries({ queryKey: ["analytics"] });
  };

  const transition = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.post(`/cases/${id}/transition`, payload),
    onSuccess: () => {
      invalidateCase();
      toast.success("Case updated");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const resolve = useMutation({
    mutationFn: () => api.post(`/cases/${id}/resolve`, { resolution_summary: resolveSummary, close: closeAfter }),
    onSuccess: () => {
      setResolveOpen(false);
      setResolveSummary("");
      invalidateCase();
      toast.success("Case resolved");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const assign = useMutation({
    mutationFn: () => api.post(`/cases/${id}/assign`, { user_id: assignUser || null, reason: "Case workspace" }),
    onSuccess: () => {
      setAssignOpen(false);
      invalidateCase();
      toast.success("Assignment updated");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const escalate = useMutation({
    mutationFn: () => api.post(`/cases/${id}/escalate`, { reason: escalateReason, priority: "URGENT" }),
    onSuccess: () => {
      setEscalateOpen(false);
      setEscalateReason("");
      invalidateCase();
      toast.success("Case escalated");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const merge = useMutation({
    mutationFn: () => api.post(`/cases/${id}/merge`, { source_case_id: mergeSource, note: "Merged from case workspace" }),
    onSuccess: () => {
      setMergeOpen(false);
      setMergeSource("");
      invalidateCase();
      toast.success("Cases merged");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const addComment = useMutation({
    mutationFn: () => api.post(`/cases/${id}/comments`, { body: comment, visibility: commentVisibility }),
    onSuccess: () => {
      setComment("");
      invalidateCase();
      toast.success("Comment added");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const investigate = useMutation({
    mutationFn: () => api.post<Investigation>(`/cases/${id}/investigations`, {}),
    onSuccess: (result) => {
      setInvestigationId(result.id);
      void queryClient.invalidateQueries({ queryKey: ["case", id, "investigations"] });
      toast.success("Investigation queued");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const acceptSuggestion = useMutation({
    mutationFn: ({ investigation, index }: { investigation: string; index: number }) =>
      api.post(`/investigations/${investigation}/suggestions/${index}/accept`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["case", id, "resolutions"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      toast.success("Resolution proposed");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const propose = useMutation({
    mutationFn: () => {
      let parameters: Record<string, unknown>;
      try {
        parameters = JSON.parse(actionParams || "{}");
      } catch {
        throw new Error("Parameters must be valid JSON.");
      }
      const latest = investigations.data?.[0];
      const evidence = (latest?.evidence ?? [])
        .filter((item) => item.is_validated)
        .map((item) => ({
          source_type: item.source_type,
          source_id: item.source_id,
          document_id: item.document_id,
          page_number: item.page_number,
          quote: item.quote,
        }));
      return api.post(`/cases/${id}/resolutions`, {
        action_type: actionType,
        description: actionDescription || "Proposed resolution",
        parameters,
        evidence,
        request_approval: requestApproval,
      });
    },
    onSuccess: () => {
      setProposeOpen(false);
      setActionDescription("");
      void queryClient.invalidateQueries({ queryKey: ["case", id, "resolutions"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      toast.success("Resolution proposed");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const execute = useMutation({
    mutationFn: (resolutionId: string) => api.post<Resolution>(`/resolutions/${resolutionId}/execute`, {}),
    onSuccess: (result) => {
      setExecuteId(null);
      void queryClient.invalidateQueries({ queryKey: ["case", id, "resolutions"] });
      invalidateCase();
      if (result.status === "FAILED") toast.error(result.error ?? "Execution failed");
      else toast.success("Resolution executed");
    },
    onError: (error) => {
      setExecuteId(null);
      toast.error(errorMessage(error));
    },
  });

  const activeInvestigation = useMemo(() => {
    if (!investigations.data?.length) return null;
    return investigations.data.find((item) => item.id === investigationId) ?? investigations.data[0];
  }, [investigations.data, investigationId]);

  useEffect(() => {
    if (activeInvestigation) setInvestigationId(activeInvestigation.id);
  }, [activeInvestigation]);

  if (detail.isError) {
    return (
      <Card>
        <ErrorState message={(detail.error as Error).message} onRetry={() => detail.refetch()} />
      </Card>
    );
  }

  const record = detail.data;

  return (
    <>
      <button
        className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)] hover:text-[var(--ink)]"
        onClick={() => navigate("/cases")}
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("cases.title")}
      </button>

      {detail.isLoading || !record ? (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="mono text-[11.5px] font-semibold text-[var(--accent)]">{record.case_number}</span>
                <StatusBadge status={record.status} />
                <PriorityBadge priority={record.priority} />
                <SeverityBadge severity={record.severity} />
                {record.sla_breached ? <Badge tone="danger">SLA breached</Badge> : null}
                <Badge tone="neutral">{record.tags.map(humanize).join(" · ") || "no tags"}</Badge>
              </div>
              <h1 className="mt-1.5 max-w-3xl text-[22px] font-semibold leading-tight">{record.title}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-[var(--muted)]">
                <span className="flex items-center gap-1.5">
                  {record.assigned_user ? (
                    <>
                      <Avatar name={record.assigned_user.full_name} color={record.assigned_user.avatar_color} size={20} />
                      {record.assigned_user.full_name}
                    </>
                  ) : (
                    t("common.unassigned")
                  )}
                </span>
                <span>Due {record.due_at ? formatDateTime(record.due_at) : "—"}</span>
                <span>Created {formatDate(record.created_at)}</span>
                <span>{formatNumber(record.exception_count)} exceptions</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {can("case:assign") ? (
                <Button size="sm" variant="secondary" onClick={() => setAssignOpen(true)}>
                  <UserPlus className="h-3.5 w-3.5" />
                  {t("cases.assign")}
                </Button>
              ) : null}
              {can("case:assign") ? (
                <Button size="sm" variant="secondary" onClick={() => setEscalateOpen(true)}>
                  <ShieldAlert className="h-3.5 w-3.5" />
                  {t("cases.escalate")}
                </Button>
              ) : null}
              {can("case:merge") ? (
                <Button size="sm" variant="secondary" onClick={() => setMergeOpen(true)}>
                  <GitMerge className="h-3.5 w-3.5" />
                  {t("cases.merge")}
                </Button>
              ) : null}
              {can("case:close") && !["RESOLVED", "CLOSED", "CANCELLED"].includes(record.status) ? (
                <Button size="sm" variant="primary" onClick={() => setResolveOpen(true)}>
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {t("cases.resolve")}
                </Button>
              ) : null}
            </div>
          </div>

          <Card>
            <Tabs defaultValue="overview">
              <div className="px-3 pt-1">
                <TabsList>
                  <TabsTrigger value="overview">{t("cases.overview")}</TabsTrigger>
                  <TabsTrigger value="investigation">{t("cases.investigation")}</TabsTrigger>
                  <TabsTrigger value="resolutions">
                    {t("cases.resolutions")}
                    {resolutions.data?.length ? <span className="ml-1 text-[10px]">({resolutions.data.length})</span> : null}
                  </TabsTrigger>
                  <TabsTrigger value="timeline">{t("cases.timeline")}</TabsTrigger>
                  <TabsTrigger value="comments">{t("cases.comments")}</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="overview" className="px-5 pb-5">
                <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
                  <div className="space-y-4">
                    <div>
                      <p className="eyebrow mb-1.5">Description</p>
                      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-[var(--ink-soft)]">
                        {record.description || "No description provided."}
                      </p>
                    </div>
                    {record.resolution_summary ? (
                      <div className="rounded-md border border-[var(--success)]/25 bg-[var(--success-soft)] px-3 py-2.5">
                        <p className="eyebrow mb-1 text-[var(--success)]">Resolution</p>
                        <p className="text-[12.5px]">{record.resolution_summary}</p>
                        <p className="mt-1 text-[10.5px] text-[var(--muted)]">
                          Resolved {record.resolved_at ? formatDateTime(record.resolved_at) : "—"}
                        </p>
                      </div>
                    ) : null}

                    <div>
                      <p className="eyebrow mb-2">{t("cases.exceptions")}</p>
                      <div className="space-y-2">
                        {record.exceptions.map((exception) => (
                          <div key={exception.id} className="rounded-md border border-[var(--line)] px-3 py-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <SeverityBadge severity={exception.severity} />
                              <span className="text-[12.5px] font-semibold">{exception.title}</span>
                              <span className="mono ml-auto text-[10.5px] text-[var(--muted)]">
                                {exception.rule_code} v{exception.rule_version}
                              </span>
                            </div>
                            <div className="mt-1 flex items-center gap-3 text-[10.5px] text-[var(--muted)]">
                              <span>{humanize(exception.exception_type)}</span>
                              <span>·</span>
                              <span>detected {exception.detection_count}×</span>
                              <span>·</span>
                              <span>{timeAgo(exception.last_detected_at)}</span>
                              <StatusBadge status={exception.status} />
                            </div>
                          </div>
                        ))}
                        {record.exceptions.length === 0 ? (
                          <p className="text-[12px] text-[var(--muted)]">No linked exceptions.</p>
                        ) : null}
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <p className="eyebrow mb-2">{t("cases.related")}</p>
                      <div className="space-y-1.5">
                        {record.links.map((link) => {
                          const path =
                            link.entity_type === "INVOICE"
                              ? `/invoices/${link.entity_id}`
                              : link.entity_type === "VENDOR"
                                ? `/vendors/${link.entity_id}`
                                : link.entity_type === "PURCHASE_ORDER"
                                  ? `/purchase-orders/${link.entity_id}`
                                  : link.entity_type === "DOCUMENT"
                                    ? `/documents/${link.entity_id}`
                                    : null;
                          const label = link.label || `${humanize(link.entity_type)} ${link.entity_id.slice(0, 8)}`;
                          return path ? (
                            <Link
                              key={link.id}
                              to={path}
                              className="flex items-center justify-between rounded-md border border-[var(--line)] px-2.5 py-2 text-[12px] hover:bg-[var(--surface-2)]"
                            >
                              <span className="flex items-center gap-2">
                                <FileText className="h-3.5 w-3.5 text-[var(--muted)]" />
                                <span>{label}</span>
                              </span>
                              <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                                {humanize(link.entity_type)}
                              </span>
                            </Link>
                          ) : (
                            <div
                              key={link.id}
                              className="flex items-center justify-between rounded-md border border-[var(--line)] px-2.5 py-2 text-[12px]"
                            >
                              <span>{label}</span>
                              <span className="text-[10px] uppercase tracking-wide text-[var(--muted)]">
                                {humanize(link.entity_type)}
                              </span>
                            </div>
                          );
                        })}
                        {record.links.length === 0 ? (
                          <p className="text-[12px] text-[var(--muted)]">No linked records.</p>
                        ) : null}
                      </div>
                    </div>

                    <div className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] p-3">
                      <p className="eyebrow mb-2">Case metadata</p>
                      <dl className="space-y-1.5 text-[11.5px]">
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--muted)]">Created by</dt>
                          <dd>{record.created_by?.full_name ?? "System"}</dd>
                        </div>
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--muted)]">First response</dt>
                          <dd>{record.first_response_at ? formatDateTime(record.first_response_at) : "—"}</dd>
                        </div>
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--muted)]">SLA target</dt>
                          <dd>{record.sla_hours} hours</dd>
                        </div>
                        <div className="flex justify-between gap-3">
                          <dt className="text-[var(--muted)]">Last activity</dt>
                          <dd>{timeAgo(record.last_activity_at)}</dd>
                        </div>
                      </dl>
                    </div>

                    {approvals.data?.length ? (
                      <div>
                        <p className="eyebrow mb-2">{t("cases.approvals")}</p>
                        {approvals.data.map((approval) => (
                          <Link
                            key={approval.id}
                            to="/approvals"
                            className="mb-1.5 flex items-center justify-between rounded-md border border-[var(--line)] px-2.5 py-2 text-[12px] hover:bg-[var(--surface-2)]"
                          >
                            <span className="truncate">{approval.title}</span>
                            <StatusBadge status={approval.status} />
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="investigation" className="px-5 pb-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-[12px] text-[var(--muted)]">
                    {aiStatus.data?.configured ? (
                      <span className="flex items-center gap-1.5">
                        <span
                          className={cn(
                            "dot",
                            aiStatus.data.available ? "text-[var(--success)]" : "text-[var(--danger)]",
                          )}
                        />
                        {aiStatus.data.provider} · {aiStatus.data.model ?? "model not set"}
                        {aiStatus.data.deterministic_stub ? (
                          <Badge tone="warning">{t("common.deterministicStub")}</Badge>
                        ) : null}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 text-[var(--warning)]">
                        <TriangleAlert className="h-3.5 w-3.5" />
                        {t("common.aiUnavailable")} — {t("common.aiUnavailableBody")}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {investigations.data?.length ? (
                      <Select
                        className="w-auto"
                        value={investigationId ?? ""}
                        onChange={(event) => setInvestigationId(event.target.value)}
                      >
                        {investigations.data.map((item) => (
                          <option key={item.id} value={item.id}>
                            {formatDateTime(item.created_at)} · {humanize(item.status)}
                          </option>
                        ))}
                      </Select>
                    ) : null}
                    <Button
                      size="sm"
                      variant="primary"
                      loading={investigate.isPending}
                      disabled={!can("investigation:run")}
                      onClick={() => investigate.mutate()}
                    >
                      <Sparkles className="h-3.5 w-3.5" />
                      {t("cases.runInvestigation")}
                    </Button>
                  </div>
                </div>

                {investigations.isLoading ? (
                  <Skeleton className="h-40" />
                ) : !activeInvestigation ? (
                  <EmptyState
                    icon={<Bot className="h-5 w-5" />}
                    title={t("cases.investigationEmpty")}
                    body={t("cases.investigationEmptyBody")}
                  />
                ) : (
                  <InvestigationPanel
                    investigation={activeInvestigation}
                    accepted={(index) => acceptSuggestion.mutate({ investigation: activeInvestigation.id, index })}
                    canAccept={can("resolution:propose")}
                  />
                )}
              </TabsContent>

              <TabsContent value="resolutions" className="px-5 pb-5">
                <div className="mb-3 flex items-center justify-between">
                  <p className="text-[12px] text-[var(--muted)]">
                    Resolutions are validated, approved when required, and executed with an audit trail.
                  </p>
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={!can("resolution:propose")}
                    onClick={() => setProposeOpen(true)}
                  >
                    {t("cases.proposeResolution")}
                  </Button>
                </div>

                {resolutions.isLoading ? (
                  <Skeleton className="h-32" />
                ) : (resolutions.data ?? []).length === 0 ? (
                  <EmptyState
                    title="No resolutions proposed"
                    body="Propose an action manually or accept an AI suggestion from the investigation tab."
                  />
                ) : (
                  <div className="space-y-2">
                    {resolutions.data?.map((resolution) => (
                      <div key={resolution.id} className="rounded-md border border-[var(--line)] p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-[12.5px] font-semibold">{humanize(resolution.action_type)}</span>
                          <StatusBadge status={resolution.status} />
                          <RiskBadge risk={resolution.risk_level} />
                          {resolution.requires_approval ? <Badge tone="warning">approval required</Badge> : null}
                          {resolution.ai_model ? <Badge tone="info">AI · {resolution.ai_model}</Badge> : null}
                          <span className="ml-auto text-[10.5px] text-[var(--muted)]">
                            {timeAgo(resolution.created_at)} · {resolution.created_by_name ?? "system"}
                          </span>
                        </div>
                        <p className="mt-1.5 text-[12px] text-[var(--ink-soft)]">{resolution.description}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {resolution.approval ? (
                            <Badge tone={resolution.approval.status === "APPROVED" ? "success" : "warning"}>
                              approval · {humanize(String(resolution.approval.status))}
                            </Badge>
                          ) : null}
                          {resolution.status === "FAILED" && resolution.error ? (
                            <span className="text-[11px] text-[var(--danger)]">{resolution.error}</span>
                          ) : null}
                          {resolution.execution_result ? (
                            <span className="mono max-w-full truncate text-[10.5px] text-[var(--muted)]">
                              {JSON.stringify(resolution.execution_result)}
                            </span>
                          ) : null}
                          <div className="ml-auto flex gap-1.5">
                            {["VALIDATED", "APPROVED"].includes(resolution.status) && can("resolution:execute") ? (
                              <Button
                                size="sm"
                                variant="primary"
                                loading={execute.isPending && executeId === resolution.id}
                                onClick={() => {
                                  setExecuteId(resolution.id);
                                  execute.mutate(resolution.id);
                                }}
                              >
                                {t("cases.execute")}
                              </Button>
                            ) : null}
                            {resolution.status === "FAILED" && can("resolution:execute") ? (
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => {
                                  setExecuteId(resolution.id);
                                  api
                                    .post(`/resolutions/${resolution.id}/retry`)
                                    .then(() => {
                                      void queryClient.invalidateQueries({ queryKey: ["case", id, "resolutions"] });
                                      toast.success("Retry queued");
                                    })
                                    .catch((error) => toast.error(errorMessage(error)))
                                    .finally(() => setExecuteId(null));
                                }}
                              >
                                {t("common.retry")}
                              </Button>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="timeline" className="px-5 pb-5">
                <div className="space-y-0">
                  {[...record.activities, ...record.comments]
                    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
                    .map((item) => (
                      <div key={item.id} className="flex gap-3 border-b border-[var(--line)] py-2.5 last:border-0">
                        <span className="mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-[var(--surface-3)]">
                          {"activity_type" in item ? (
                            <CircleDashed className="h-3 w-3 text-[var(--muted)]" />
                          ) : (
                            <FileText className="h-3 w-3 text-[var(--muted)]" />
                          )}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[12.5px]">
                            {"activity_type" in item ? item.summary : item.body}
                          </p>
                          <p className="text-[10.5px] text-[var(--muted)]">
                            {"activity_type" in item ? item.actor_name ?? "System" : item.author_name ?? "System"}
                            {" · "}
                            {formatDateTime(item.created_at)}
                            {"activity_type" in item ? ` · ${humanize(item.activity_type)}` : " · comment"}
                          </p>
                        </div>
                      </div>
                    ))}
                </div>
              </TabsContent>

              <TabsContent value="comments" className="px-5 pb-5">
                {can("case:comment") ? (
                  <div className="mb-4 rounded-md border border-[var(--line)] p-3">
                    <Textarea
                      rows={3}
                      placeholder={t("cases.commentPlaceholder")}
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                    />
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <Select
                        className="w-auto"
                        value={commentVisibility}
                        onChange={(event) => setCommentVisibility(event.target.value as "INTERNAL" | "EXTERNAL")}
                      >
                        <option value="INTERNAL">{t("cases.internal")}</option>
                        <option value="EXTERNAL">{t("cases.external")}</option>
                      </Select>
                      <Button
                        size="sm"
                        variant="primary"
                        loading={addComment.isPending}
                        disabled={!comment.trim()}
                        onClick={() => addComment.mutate()}
                      >
                        {t("cases.addComment")}
                      </Button>
                    </div>
                  </div>
                ) : null}
                <div className="space-y-3">
                  {[...(record.comments ?? [])].reverse().map((item) => (
                    <div key={item.id} className="rounded-md border border-[var(--line)] p-3">
                      <div className="flex items-center gap-2">
                        <Avatar name={item.author_name} size={22} />
                        <span className="text-[12px] font-semibold">{item.author_name ?? "System"}</span>
                        <Badge tone={item.visibility === "INTERNAL" ? "neutral" : "info"}>{humanize(item.visibility)}</Badge>
                        <span className="ml-auto text-[10.5px] text-[var(--muted)]">{timeAgo(item.created_at)}</span>
                      </div>
                      <p className="mt-1.5 whitespace-pre-wrap text-[12.5px]">{item.body}</p>
                    </div>
                  ))}
                  {(record.comments ?? []).length === 0 ? (
                    <p className="py-6 text-center text-[12px] text-[var(--muted)]">No comments yet.</p>
                  ) : null}
                </div>
              </TabsContent>
            </Tabs>
          </Card>
        </>
      )}

      <Dialog open={resolveOpen} onOpenChange={setResolveOpen}>
        <DialogContent title={t("cases.resolve")} description={`${record?.case_number ?? ""} · ${record?.title ?? ""}`}>
          <div className="space-y-4">
            <Field label={t("cases.resolveSummary")}>
              <Textarea rows={4} value={resolveSummary} onChange={(event) => setResolveSummary(event.target.value)} />
            </Field>
            <label className="flex items-center gap-2 text-[12px]">
              <input type="checkbox" checked={closeAfter} onChange={(event) => setCloseAfter(event.target.checked)} />
              {t("cases.closeAfter")}
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setResolveOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" loading={resolve.isPending} disabled={resolveSummary.trim().length < 3} onClick={() => resolve.mutate()}>
                {t("cases.resolve")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
        <DialogContent title={t("cases.assign")}>
          <div className="space-y-4">
            <Field label={t("cases.assignee")}>
              <Select value={assignUser} onChange={(event) => setAssignUser(event.target.value)}>
                <option value="">{t("common.unassigned")}</option>
                {(members.data ?? []).map((member) => (
                  <option key={member.id} value={member.id}>
                    {member.full_name} · {humanize(member.role)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setAssignOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" loading={assign.isPending} onClick={() => assign.mutate()}>
                {t("common.save")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={escalateOpen} onOpenChange={setEscalateOpen}>
        <DialogContent title={t("cases.escalate")} description="Raises priority and notifies operations managers.">
          <div className="space-y-4">
            <Field label={t("common.reason")}>
              <Textarea rows={3} value={escalateReason} onChange={(event) => setEscalateReason(event.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEscalateOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="danger" loading={escalate.isPending} disabled={escalateReason.trim().length < 3} onClick={() => escalate.mutate()}>
                {t("cases.escalate")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent title={t("cases.merge")} description={t("cases.mergeHint")}>
          <div className="space-y-4">
            <Field label={t("cases.sourceCase")}>
              <Input value={mergeSource} onChange={(event) => setMergeSource(event.target.value)} placeholder="UUID of the case to merge into this one" />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setMergeOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="danger" loading={merge.isPending} disabled={mergeSource.trim().length < 10} onClick={() => merge.mutate()}>
                {t("cases.merge")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={proposeOpen} onOpenChange={setProposeOpen}>
        <DialogContent title={t("cases.proposeResolution")} description="Actions are validated and may require approval." wide>
          <div className="space-y-4">
            <Field label={t("cases.action")}>
              <Select
                value={actionType}
                onChange={(event) => {
                  setActionType(event.target.value);
                  setActionParams(JSON.stringify(ACTION_TEMPLATES[event.target.value] ?? {}, null, 2));
                }}
              >
                {(actionCatalog.data ?? []).map((action) => (
                  <option key={action.action_type} value={action.action_type}>
                    {action.label} · {humanize(action.default_risk)} risk
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("common.description")}>
              <Textarea rows={2} value={actionDescription} onChange={(event) => setActionDescription(event.target.value)} />
            </Field>
            <Field label={t("cases.parameters")} hint="JSON">
              <Textarea
                className="mono text-[11px]"
                rows={7}
                value={actionParams}
                onChange={(event) => setActionParams(event.target.value)}
              />
            </Field>
            <label className="flex items-center gap-2 text-[12px]">
              <input type="checkbox" checked={requestApproval} onChange={(event) => setRequestApproval(event.target.checked)} />
              {t("cases.requestApproval")}
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setProposeOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" loading={propose.isPending} onClick={() => propose.mutate()}>
                {t("common.create")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={Boolean(executeId)}
        onOpenChange={(open) => !open && setExecuteId(null)}
        title={t("cases.execute")}
        description="The action will run immediately and every step is recorded in the audit trail."
        confirmLabel={t("cases.execute")}
        loading={execute.isPending}
        onConfirm={() => executeId && execute.mutate(executeId)}
      />

      {record && ["OPEN", "INVESTIGATING", "REOPENED"].includes(record.status) ? (
        <div className="mt-3 flex justify-end">
          <Button variant="ghost" size="sm" onClick={() => transition.mutate({ status: "INVESTIGATING", note: "Started investigation" })}>
            Mark investigating
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : null}
    </>
  );
}

function InvestigationPanel({
  investigation,
  canAccept,
  accepted,
}: {
  investigation: Investigation;
  canAccept: boolean;
  accepted: (index: number) => void;
}) {
  const { t } = useI18n();
  if (investigation.status === "QUEUED" || investigation.status === "RUNNING") {
    return (
      <div className="rounded-md border border-[var(--line)] bg-[var(--surface-2)] p-4">
        <div className="flex items-center gap-2 text-[12.5px]">
          <CircleDashed className="h-4 w-4 animate-spin text-[var(--accent)]" />
          Investigation {humanize(investigation.status).toLowerCase()} · the pipeline is retrieving evidence and calling the model.
        </div>
        <div className="mt-3 space-y-2">
          <Skeleton className="h-3 w-4/5" />
          <Skeleton className="h-3 w-3/5" />
        </div>
      </div>
    );
  }

  if (investigation.status === "FAILED") {
    return (
      <div className="rounded-md border border-[var(--danger)]/25 bg-[var(--danger-soft)] p-4 text-[12.5px] text-[var(--danger)]">
        <div className="flex items-center gap-2 font-semibold">
          <XCircle className="h-4 w-4" />
          Investigation failed · {investigation.error_code ?? "error"}
        </div>
        <p className="mt-1">{investigation.error}</p>
      </div>
    );
  }

  const validEvidence = investigation.evidence.filter((item) => !item.is_contradicting);
  const contradictions = investigation.evidence.filter((item) => item.is_contradicting);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-[1.6fr_1fr]">
        <div className="rounded-md border border-[var(--line)] p-3">
          <p className="eyebrow mb-1.5">Summary</p>
          <p className="text-[13px] leading-relaxed">{investigation.summary}</p>
          {investigation.root_cause ? (
            <div className="mt-3 rounded border border-[var(--accent)]/25 bg-[var(--accent-soft)] px-3 py-2">
              <p className="eyebrow mb-1 text-[var(--accent)]">{`Root cause`}</p>
              <p className="text-[12.5px]">{investigation.root_cause}</p>
            </div>
          ) : (
            <div className="mt-3 flex items-start gap-2 rounded border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-3 py-2 text-[12px] text-[var(--warning)]">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              The root cause was withheld: evidence was insufficient or failed validation.
            </div>
          )}
        </div>
        <div className="space-y-2 rounded-md border border-[var(--line)] p-3 text-[12px]">
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">{`Risk`}</span>
            <RiskBadge risk={investigation.risk_level} />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">{`Confidence (heuristic)`}</span>
            <span className="num font-semibold">{confidence(investigation.confidence)}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">Evidence</span>
            <span className="num font-semibold">
              {investigation.evidence_count - investigation.invalid_evidence_count}/{investigation.evidence_count} validated
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">Model</span>
            <span className="truncate">{investigation.model ?? "—"}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">Prompt</span>
            <span className="mono text-[10.5px]">{investigation.prompt_version}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--muted)]">Tokens / cost</span>
            <span className="num">
              {formatNumber(investigation.input_tokens + investigation.output_tokens)} · $
              {(investigation.cost_usd ?? 0).toFixed(4)}
            </span>
          </div>
          {investigation.requires_human_review ? <Badge tone="warning">{`Requires human review`}</Badge> : null}
        </div>
      </div>

      {investigation.invalid_evidence_count > 0 ? (
        <div className="rounded-md border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3 py-2 text-[12px] text-[var(--danger)]">
          {`${investigation.invalid_evidence_count} evidence item(s) failed validation and are excluded from the root-cause assessment.`}
        </div>
      ) : null}

      <div>
        <p className="eyebrow mb-2">Evidence</p>
        <div className="space-y-2">
          {validEvidence.map((item) => (
            <div
              key={item.id}
              className={cn(
                "rounded-md border px-3 py-2",
                item.is_validated ? "border-[var(--line)]" : "border-[var(--danger)]/35 bg-[var(--danger-soft)]",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="neutral">{humanize(item.source_type)}</Badge>
                {item.page_number ? <Badge tone="neutral">page {item.page_number}</Badge> : null}
                {item.field_name ? <Badge tone="neutral">{item.field_name}</Badge> : null}
                {item.is_validated ? (
                  <Badge tone="success">
                    <CheckCircle2 className="h-3 w-3" /> validated
                  </Badge>
                ) : (
                  <Badge tone="danger">{item.validation_error ?? "invalid"}</Badge>
                )}
              </div>
              <blockquote className="mt-1.5 border-l-2 border-[var(--line-strong)] pl-2.5 text-[12px] italic text-[var(--ink-soft)]">
                “{item.quote}”
              </blockquote>
              {item.relationship ? <p className="mt-1 text-[10.5px] text-[var(--muted)]">{item.relationship}</p> : null}
            </div>
          ))}
          {validEvidence.length === 0 ? <p className="text-[12px] text-[var(--muted)]">No evidence returned.</p> : null}
        </div>
      </div>

      {contradictions.length > 0 ? (
        <div>
          <p className="eyebrow mb-2">Contradicting evidence</p>
          {contradictions.map((item) => (
            <blockquote key={item.id} className="rounded border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-3 py-2 text-[12px]">
              “{item.quote}”
            </blockquote>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="eyebrow mb-1.5">{t("cases.hypotheses")}</p>
          <div className="space-y-1.5">
            {investigation.root_cause_hypotheses.map((item, index) => (
              <div key={index} className="rounded border border-[var(--line)] px-2.5 py-2 text-[12px]">
                <div className="flex items-center gap-1.5">
                  <Badge tone={item.likelihood === "high" ? "warning" : "neutral"}>{humanize(String(item.likelihood))}</Badge>
                  <span>{item.hypothesis}</span>
                </div>
              </div>
            ))}
            {investigation.root_cause_hypotheses.length === 0 ? (
              <p className="text-[12px] text-[var(--muted)]">None recorded.</p>
            ) : null}
          </div>
        </div>
        <div>
          <p className="eyebrow mb-1.5">{t("cases.missingInfo")}</p>
          <ul className="list-inside list-disc space-y-1 text-[12px] text-[var(--ink-soft)]">
            {investigation.missing_information.map((item) => (
              <li key={item}>{item}</li>
            ))}
            {investigation.missing_information.length === 0 ? <li className="text-[var(--muted)]">None</li> : null}
          </ul>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="eyebrow mb-1.5">{t("cases.limitations")}</p>
          <ul className="list-inside list-disc space-y-1 text-[11.5px] text-[var(--muted)]">
            {investigation.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="eyebrow mb-1.5">{t("cases.requiredActions")}</p>
          <ul className="list-inside list-disc space-y-1 text-[11.5px] text-[var(--muted)]">
            {investigation.required_actions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>

      <div>
        <p className="eyebrow mb-2">{t("cases.suggestedResolutions")}</p>
        <div className="grid gap-2 md:grid-cols-2">
          {investigation.suggested_resolutions.map((suggestion, index) => (
            <div key={index} className="rounded-md border border-[var(--line)] p-3">
              <div className="flex items-center gap-1.5">
                <span className="text-[12.5px] font-semibold">{humanize(suggestion.action_type)}</span>
                <RiskBadge risk={suggestion.risk_level} />
              </div>
              <p className="mt-1 text-[12px]">{suggestion.description}</p>
              <p className="mt-1 text-[11px] text-[var(--muted)]">{suggestion.rationale}</p>
              <Button
                size="sm"
                variant="outline"
                className="mt-2"
                disabled={!canAccept}
                onClick={() => accepted(index)}
              >
                {t("cases.acceptSuggestion")}
              </Button>
            </div>
          ))}
          {investigation.suggested_resolutions.length === 0 ? (
            <p className="text-[12px] text-[var(--muted)]">No suggestions.</p>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-t border-[var(--line)] pt-2 text-[10.5px] text-[var(--muted)]">
        <span className="flex items-center gap-1">
          <Bot className="h-3 w-3" />
          {investigation.provider} · {investigation.model}
        </span>
        <span>{formatDateTime(investigation.completed_at ?? investigation.created_at)}</span>
        <span>{formatNumber(investigation.latency_ms ?? 0)} ms</span>
        <span className="ml-auto mono">{investigation.id.slice(0, 8)}</span>
      </div>
    </div>
  );
}

// Local component kept alongside the page it serves.
