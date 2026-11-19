import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Inbox, ShieldCheck, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  RiskBadge,
  Skeleton,
  StatusBadge,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
} from "@/components/ui";
import type { Approval, Page } from "@/types/api";

export function ApprovalsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [scope, setScope] = useState<"pending" | "all" | "mine">("pending");
  const [selected, setSelected] = useState<Approval | null>(null);
  const [comment, setComment] = useState("");
  const [executeAfter, setExecuteAfter] = useState(false);

  const params = {
    page,
    page_size: 20,
    status: scope === "pending" ? "PENDING" : undefined,
    mine: scope === "mine" ? true : undefined,
  };

  const approvals = useQuery({
    queryKey: ["approvals", params],
    queryFn: () => api.get<Page<Approval>>(`/approvals${buildQuery(params)}`),
    refetchInterval: 20_000,
  });

  const stats = useQuery({
    queryKey: ["approvals", "stats"],
    queryFn: () => api.get<{ pending: number; overdue: number; approved_today: number; rejected_today: number; average_decision_hours: number; by_risk: Record<string, number> }>("/approvals/stats"),
  });

  const decide = useMutation({
    mutationFn: ({ approve }: { approve: boolean }) =>
      api.post(`/approvals/${selected?.id}/${approve ? "approve" : "reject"}`, {
        comment: comment || undefined,
        execute_after_approval: approve && executeAfter,
      }),
    onSuccess: (result: any) => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
      if (result.execution_error) toast.error(result.execution_error);
      else toast.success("Decision recorded");
      setSelected(null);
      setComment("");
      setExecuteAfter(false);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const items = approvals.data?.items ?? [];

  return (
    <>
      <PageHeader title={t("approvals.title")} subtitle={t("approvals.subtitle")} />

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          { label: t("approvals.pending"), value: stats.data?.pending ?? 0, icon: <Clock3 className="h-4 w-4 text-[var(--warning)]" /> },
          { label: t("common.overdue"), value: stats.data?.overdue ?? 0, icon: <XCircle className="h-4 w-4 text-[var(--danger)]" /> },
          { label: "Approved today", value: stats.data?.approved_today ?? 0, icon: <CheckCircle2 className="h-4 w-4 text-[var(--success)]" /> },
          { label: "Avg. decision", value: `${(stats.data?.average_decision_hours ?? 0).toFixed(1)}h`, icon: <ShieldCheck className="h-4 w-4 text-[var(--info)]" /> },
        ].map((item) => (
          <Card key={item.label} className="kpi">
            <div className="flex items-center justify-between">
              <span className="eyebrow">{item.label}</span>
              {item.icon}
            </div>
            <p className="kpi-value">{item.value}</p>
          </Card>
        ))}
      </div>

      <Card>
        <div className="px-3 pt-2">
          <Tabs defaultValue="pending" onValueChange={(value) => { setScope(value as typeof scope); setPage(1); }}>
            <TabsList>
              <TabsTrigger value="pending">{t("approvals.pending")}</TabsTrigger>
              <TabsTrigger value="all">{t("approvals.allDecisions")}</TabsTrigger>
              <TabsTrigger value="mine">{t("approvals.myRequests")}</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        {approvals.isLoading ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-16" />)}</div>
        ) : approvals.isError ? (
          <ErrorState message={(approvals.error as Error).message} onRetry={() => approvals.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState icon={<Inbox className="h-5 w-5" />} title={t("approvals.noPending")} body="High-risk actions that need a decision will appear here." />
        ) : (
          <div className="divide-y divide-[var(--line)]">
            {items.map((approval) => (
              <button
                key={approval.id}
                className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-[var(--surface-2)]"
                onClick={() => { setSelected(approval); setComment(""); setExecuteAfter(false); }}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-semibold">{approval.title}</span>
                    <StatusBadge status={approval.status} />
                    <RiskBadge risk={approval.risk_level} />
                    {approval.overdue ? <Badge tone="danger">{t("common.overdue")}</Badge> : null}
                  </div>
                  <p className="mt-0.5 line-clamp-1 text-[11.5px] text-[var(--muted)]">
                    {approval.case_number} · {approval.case_title} · {approval.action_type}
                  </p>
                </div>
                <div className="flex items-center gap-4 text-[11px] text-[var(--muted)]">
                  <span className="hidden items-center gap-1 sm:flex">
                    {approval.requester ? <Avatar name={approval.requester.full_name} size={20} /> : null}
                    {approval.requester?.full_name}
                  </span>
                  <span>expires {approval.expires_at ? timeAgo(approval.expires_at) : "—"}</span>
                  {approval.can_decide ? <Badge tone="accent">action required</Badge> : null}
                </div>
              </button>
            ))}
          </div>
        )}
        {approvals.data ? (
          <Pagination page={approvals.data.meta.page} pages={approvals.data.meta.pages} total={approvals.data.meta.total} pageSize={approvals.data.meta.page_size} onPage={setPage} />
        ) : null}
      </Card>

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        {selected ? (
          <DialogContent title={selected.title} description={`${selected.case_number} · ${selected.action_type}`} wide>
            <div className="space-y-4">
              <div className="grid gap-3 text-[12px] sm:grid-cols-4">
                <div><p className="eyebrow">{t("approvals.risk")}</p><div className="mt-1"><RiskBadge risk={selected.risk_level} /></div></div>
                <div><p className="eyebrow">{t("common.status")}</p><div className="mt-1"><StatusBadge status={selected.status} /></div></div>
                <div><p className="eyebrow">{t("approvals.expires")}</p><p className="mt-1">{selected.expires_at ? formatDateTime(selected.expires_at) : "—"}</p></div>
                <div><p className="eyebrow">{t("approvals.requester")}</p><p className="mt-1">{selected.requester?.full_name ?? "—"}</p></div>
              </div>

              {selected.description ? <p className="text-[12.5px]">{selected.description}</p> : null}

              <div>
                <p className="eyebrow mb-1">Action parameters</p>
                <pre className="mono max-h-[160px] overflow-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-2.5 text-[10.5px]">{JSON.stringify(selected.parameters, null, 2)}</pre>
              </div>
              <div>
                <p className="eyebrow mb-1">{t("common.evidence")}</p>
                <pre className="mono max-h-[200px] overflow-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-2.5 text-[10.5px]">{JSON.stringify(selected.evidence, null, 2)}</pre>
              </div>

              {selected.decisions?.length ? (
                <div>
                  <p className="eyebrow mb-1">Decision history</p>
                  {selected.decisions.map((decision) => (
                    <div key={decision.id} className="rounded border border-[var(--line)] px-2.5 py-2 text-[11.5px]">
                      <span className={cn("font-semibold", decision.decision === "APPROVED" ? "text-[var(--success)]" : "text-[var(--danger)]")}>{decision.decision}</span>
                      {" · "}{decision.decided_by_name ?? "—"} · {formatDateTime(decision.created_at)}
                      {decision.comment ? <p className="mt-0.5 text-[11px] text-[var(--muted)]">{decision.comment}</p> : null}
                    </div>
                  ))}
                </div>
              ) : null}

              {selected.can_decide && selected.status === "PENDING" ? (
                <div className="space-y-2 border-t border-[var(--line)] pt-3">
                  <Textarea rows={3} placeholder={t("approvals.commentPlaceholder")} value={comment} onChange={(event) => setComment(event.target.value)} />
                  <label className="flex items-center gap-2 text-[12px]">
                    <input type="checkbox" checked={executeAfter} onChange={(event) => setExecuteAfter(event.target.checked)} />
                    {t("approvals.approveAndExecute")}
                  </label>
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="secondary" onClick={() => { setSelected(null); window.location.assign(`/cases/${selected.case_id}`); }}>
                      Open case
                    </Button>
                    <Button variant="danger" loading={decide.isPending} onClick={() => decide.mutate({ approve: false })}>
                      {t("approvals.reject")}
                    </Button>
                    <Button variant="primary" loading={decide.isPending} onClick={() => decide.mutate({ approve: true })}>
                      {t("approvals.approve")}
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="rounded border border-[var(--line)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] text-[var(--muted)]">
                  {selected.status === "PENDING" ? "This request is assigned to another approver or is your own request." : "This request has been decided."}
                </p>
              )}
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}
