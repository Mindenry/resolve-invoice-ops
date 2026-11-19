import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { humanize, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  Input,
  PageHeader,
  Pagination,
  PriorityBadge,
  Select,
  StatusBadge,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { CaseSummary, Page } from "@/types/api";

const STATUSES = [
  "OPEN",
  "INVESTIGATING",
  "AWAITING_INFORMATION",
  "AWAITING_APPROVAL",
  "RESOLUTION_IN_PROGRESS",
  "RESOLVED",
  "CLOSED",
];
const PRIORITIES = ["URGENT", "HIGH", "MEDIUM", "LOW"];

export function CasesPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(params.get("search") ?? "");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [openOnly, setOpenOnly] = useState(params.get("open_only") === "true");
  const [breached, setBreached] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [assignee, setAssignee] = useState("");

  useEffect(() => {
    setSearch(params.get("search") ?? "");
    setOpenOnly(params.get("open_only") === "true");
  }, [params]);

  const queryParams = useMemo(
    () => ({
      page,
      page_size: 25,
      search: search || undefined,
      status: status || undefined,
      priority: priority || undefined,
      open_only: openOnly || undefined,
      breached: breached || undefined,
      sort: "last_activity_at",
      order: "desc",
    }),
    [page, search, status, priority, openOnly, breached],
  );

  const list = useQuery({
    queryKey: ["cases", queryParams],
    queryFn: () => api.get<Page<CaseSummary>>(`/cases${buildQuery(queryParams)}`),
  });

  const members = useQuery({
    queryKey: ["members", "assignable"],
    queryFn: () =>
      api.get<{ id: string; full_name: string; email: string; role: string }[]>(
        "/organizations/members/assignable",
      ),
    enabled: bulkOpen && can("case:assign"),
  });

  const bulkAssign = useMutation({
    mutationFn: () => api.post("/cases/bulk/assign", { case_ids: selected, user_id: assignee || null }),
    onSuccess: () => {
      toast.success("Cases assigned");
      setBulkOpen(false);
      setSelected([]);
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const toggle = (id: string) => {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  };

  const columns: Column<CaseSummary>[] = [
    ...(can("case:assign")
      ? [
          {
            key: "select",
            header: "",
            width: "36px",
            render: (row: CaseSummary) => (
              <input
                type="checkbox"
                checked={selected.includes(row.id)}
                onClick={(event) => event.stopPropagation()}
                onChange={() => toggle(row.id)}
                aria-label={`Select ${row.case_number}`}
              />
            ),
          } as Column<CaseSummary>,
        ]
      : []),
    {
      key: "case",
      header: t("cases.caseNumber"),
      render: (row) => (
        <div>
          <div className="mono text-[11.5px] font-semibold text-[var(--accent)]">{row.case_number}</div>
          <div className="max-w-[280px] truncate text-[12.5px]">{row.title}</div>
        </div>
      ),
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "priority",
      header: t("common.priority"),
      render: (row) => <PriorityBadge priority={row.priority} />,
    },
    {
      key: "severity",
      header: t("common.severity"),
      render: (row) => <Badge tone={row.severity === "CRITICAL" ? "danger" : row.severity === "HIGH" ? "warning" : "neutral"}>{humanize(row.severity)}</Badge>,
    },
    {
      key: "assignee",
      header: t("cases.assignee"),
      render: (row) =>
        row.assigned_user ? (
          <span className="flex items-center gap-1.5 text-[12px]">
            <Avatar name={row.assigned_user.full_name} color={row.assigned_user.avatar_color} size={22} />
            <span className="hidden lg:inline">{row.assigned_user.full_name}</span>
          </span>
        ) : (
          <span className="text-[11.5px] text-[var(--muted)]">{t("common.unassigned")}</span>
        ),
    },
    {
      key: "exceptions",
      header: t("cases.exceptions"),
      align: "right",
      render: (row) => <span className="num text-[12px]">{row.exception_count}</span>,
    },
    {
      key: "due",
      header: t("common.due"),
      render: (row) => (
        <span className={cn("text-[11.5px]", row.sla_breached ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
          {row.due_at ? timeAgo(row.due_at) : "—"}
        </span>
      ),
    },
    {
      key: "activity",
      header: t("common.activity"),
      render: (row) => <span className="text-[11.5px] text-[var(--muted)]">{timeAgo(row.last_activity_at)}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("cases.title")}
        subtitle={t("cases.subtitle")}
        actions={
          selected.length > 0 && can("case:assign") ? (
            <Button variant="primary" size="sm" onClick={() => setBulkOpen(true)}>
              <Users className="h-3.5 w-3.5" />
              {t("cases.bulkAssign")} ({selected.length})
            </Button>
          ) : undefined
        }
      />

      <Card>
        <div className="toolbar">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <Input
              className="pl-8"
              placeholder={t("common.search")}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
                setParams((current) => {
                  const next = new URLSearchParams(current);
                  if (event.target.value) next.set("search", event.target.value);
                  else next.delete("search");
                  return next;
                });
              }}
            />
          </div>
          <Select
            className="w-auto min-w-[150px]"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
          <Select
            className="w-auto min-w-[130px]"
            value={priority}
            onChange={(event) => {
              setPriority(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All priorities</option>
            {PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
          <label className="flex items-center gap-1.5 text-[12px]">
            <input
              type="checkbox"
              checked={openOnly}
              onChange={(event) => {
                setOpenOnly(event.target.checked);
                setPage(1);
              }}
            />
            {t("cases.openOnly")}
          </label>
          <label className="flex items-center gap-1.5 text-[12px]">
            <input
              type="checkbox"
              checked={breached}
              onChange={(event) => {
                setBreached(event.target.checked);
                setPage(1);
              }}
            />
            {t("cases.breached")}
          </label>
        </div>

        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/cases/${row.id}`)}
          empty={<EmptyState title={t("cases.noCases")} body="Adjust the filters or run detection on the exception queue." />}
        />
        {list.data ? (
          <Pagination
            page={list.data.meta.page}
            pages={list.data.meta.pages}
            total={list.data.meta.total}
            pageSize={list.data.meta.page_size}
            onPage={setPage}
          />
        ) : null}
      </Card>

      <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
        <DialogContent title={t("cases.bulkAssign")} description={`${selected.length} selected case(s)`}>
          <div className="space-y-4">
            <label className="label">{t("cases.selectAssignee")}</label>
            <Select value={assignee} onChange={(event) => setAssignee(event.target.value)}>
              <option value="">{t("common.unassigned")}</option>
              {(members.data ?? []).map((member) => (
                <option key={member.id} value={member.id}>
                  {member.full_name} · {humanize(member.role)}
                </option>
              ))}
            </Select>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setBulkOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button variant="primary" loading={bulkAssign.isPending} onClick={() => bulkAssign.mutate()}>
                {t("common.apply")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
