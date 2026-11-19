import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Filter, Play, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { formatNumber, humanize, timeAgo } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  Input,
  PageHeader,
  Pagination,
  Select,
  SeverityBadge,
  StatusBadge,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { ExceptionRecord, Page } from "@/types/api";

const EXCEPTION_TYPES = [
  "DUPLICATE_INVOICE",
  "AMOUNT_MISMATCH",
  "VENDOR_MISMATCH",
  "MISSING_PURCHASE_ORDER",
  "MISSING_DOCUMENTS",
  "TAX_DISCREPANCY",
  "INVALID_INVOICE_DATE",
  "DUPLICATE_VENDOR",
  "EXTRACTION_ANOMALY",
  "INTEGRATION_FAILURE",
];

const STATUSES = ["OPEN", "ACKNOWLEDGED", "LINKED", "RESOLVED", "IGNORED"];
const SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export function ExceptionsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("OPEN");
  const [selected, setSelected] = useState<ExceptionRecord | null>(null);
  const [actionNote, setActionNote] = useState("");

  const params = useMemo(
    () => ({
      page,
      page_size: 25,
      search: search || undefined,
      exception_type: type || undefined,
      severity: severity || undefined,
      status: status || undefined,
      sort: "last_detected_at",
      order: "desc",
    }),
    [page, search, type, severity, status],
  );

  const list = useQuery({
    queryKey: ["exceptions", params],
    queryFn: () => api.get<Page<ExceptionRecord>>(`/exceptions${buildQuery(params)}`),
  });

  const summary = useQuery({
    queryKey: ["exceptions", "summary"],
    queryFn: () => api.get<{ total: number; open_count: number; by_type: { key: string; label: string; count: number }[]; by_severity: { key: string; count: number }[] }>("/exceptions/summary"),
  });

  const saved = useQuery({
    queryKey: ["saved-filters", "exceptions"],
    queryFn: () => api.get<{ id: string; name: string; query: Record<string, any> }[]>("/saved-filters?resource=exceptions"),
  });

  const scan = useMutation({
    mutationFn: () =>
      api.post<{ created_exceptions: number; updated_exceptions: number; opened_cases: number }>("/exceptions/scan", {
        include_invoices: true,
        include_vendors: true,
        include_integrations: true,
        limit: 100,
      }),
    onSuccess: (result) => {
      toast.success(
        t("exceptions.scanComplete", { created: result.created_exceptions, updated: result.updated_exceptions }),
      );
      void queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      void queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const triage = useMutation({
    mutationFn: ({ id, status: next, note }: { id: string; status: string; note?: string }) =>
      api.post(`/exceptions/${id}/status`, { status: next, note }),
    onSuccess: () => {
      toast.success("Exception updated");
      setSelected(null);
      setActionNote("");
      void queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const saveFilter = async () => {
    const name = window.prompt("Name this filter");
    if (!name) return;
    try {
      await api.post("/saved-filters", { resource: "exceptions", name, query: params });
      toast.success("Filter saved");
      void queryClient.invalidateQueries({ queryKey: ["saved-filters"] });
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const columns: Column<ExceptionRecord>[] = [
    {
      key: "title",
      header: "Exception",
      render: (row) => (
        <div className="max-w-[360px]">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{row.title}</span>
            {row.is_demo ? <Badge tone="neutral">demo</Badge> : null}
          </div>
          <p className="line-clamp-1 text-[11.5px] text-[var(--muted)]">{row.description}</p>
        </div>
      ),
    },
    {
      key: "severity",
      header: t("common.severity"),
      render: (row) => <SeverityBadge severity={row.severity} />,
    },
    {
      key: "type",
      header: t("common.type"),
      render: (row) => <span className="text-[12px]">{humanize(row.exception_type)}</span>,
    },
    {
      key: "case",
      header: t("common.case"),
      render: (row) =>
        row.case_number ? (
          <span className="mono text-[11.5px] font-semibold text-[var(--accent)]">{row.case_number}</span>
        ) : (
          <span className="text-[11.5px] text-[var(--muted)]">{t("exceptions.unlinked")}</span>
        ),
    },
    {
      key: "rule",
      header: t("exceptions.ruleName"),
      render: (row) => (
        <span className="mono text-[10.5px] text-[var(--muted)]">
          {row.rule_code} v{row.rule_version}
        </span>
      ),
    },
    {
      key: "detected",
      header: t("exceptions.detected"),
      render: (row) => <span className="num text-[11.5px]">{timeAgo(row.last_detected_at)}</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => <StatusBadge status={row.status} />,
    },
  ];

  const payload = selected?.evidence ?? {};

  return (
    <>
      <PageHeader
        title={t("exceptions.title")}
        subtitle={t("exceptions.subtitle")}
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => void saveFilter()}>
              <Bookmark className="h-3.5 w-3.5" />
              Save filter
            </Button>
            {can("exception:triage") ? (
              <Button variant="primary" size="sm" loading={scan.isPending} onClick={() => scan.mutate()}>
                <Play className="h-3.5 w-3.5" />
                {scan.isPending ? t("exceptions.scanning") : t("exceptions.scan")}
              </Button>
            ) : null}
          </>
        }
      >
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-[var(--muted)]">
          <span className="num rounded bg-[var(--surface-3)] px-1.5 py-0.5 font-semibold text-[var(--ink-soft)]">
            {formatNumber(summary.data?.total ?? 0)} total
          </span>
          <span className="num rounded bg-[var(--danger-soft)] px-1.5 py-0.5 font-semibold text-[var(--danger)]">
            {formatNumber(summary.data?.by_severity.find((item) => item.key === "HIGH")?.count ?? 0)} high
          </span>
          <span className="num rounded bg-[var(--warning-soft)] px-1.5 py-0.5 font-semibold text-[var(--warning)]">
            {formatNumber(summary.data?.open_count ?? 0)} open
          </span>
          {saved.data?.length ? (
            <div className="flex items-center gap-1">
              <Filter className="h-3 w-3" />
              {saved.data.map((filter) => (
                <button
                  key={filter.id}
                  className="rounded border border-[var(--line)] px-1.5 py-0.5 hover:bg-[var(--surface-3)]"
                  onClick={() => {
                    const query = filter.query as Record<string, any>;
                    setSearch(String(query.search ?? ""));
                    setType(String(query.exception_type ?? ""));
                    setSeverity(String(query.severity ?? ""));
                    setStatus(String(query.status ?? ""));
                    setPage(1);
                  }}
                >
                  {filter.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </PageHeader>

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
              }}
            />
          </div>
          <Select
            className="w-auto min-w-[150px]"
            value={type}
            onChange={(event) => {
              setType(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All types</option>
            {EXCEPTION_TYPES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
          <Select
            className="w-auto min-w-[125px]"
            value={severity}
            onChange={(event) => {
              setSeverity(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All severities</option>
            {SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
          <Select
            className="w-auto min-w-[130px]"
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
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch("");
              setType("");
              setSeverity("");
              setStatus("OPEN");
              setPage(1);
            }}
          >
            {t("common.reset")}
          </Button>
        </div>

        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => setSelected(row)}
          empty={
            <EmptyState
              title={t("common.emptyTitle")}
              body="No exceptions match the current filters."
              action={
                can("exception:triage") ? (
                  <Button size="sm" variant="secondary" onClick={() => scan.mutate()}>
                    {t("exceptions.scan")}
                  </Button>
                ) : undefined
              }
            />
          }
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

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        {selected ? (
          <DialogContent title={selected.title} description={`${humanize(selected.exception_type)} · ${selected.rule_code} v${selected.rule_version}`} wide>
            <div className="space-y-4">
              <p className="text-[12.5px] text-[var(--ink-soft)]">{selected.description}</p>

              <div className="grid grid-cols-2 gap-3 text-[12px] sm:grid-cols-4">
                <div>
                  <p className="eyebrow">Severity</p>
                  <div className="mt-1"><SeverityBadge severity={selected.severity} /></div>
                </div>
                <div>
                  <p className="eyebrow">{t("common.status")}</p>
                  <div className="mt-1"><StatusBadge status={selected.status} /></div>
                </div>
                <div>
                  <p className="eyebrow">{t("exceptions.detections")}</p>
                  <p className="num mt-1 font-semibold">{selected.detection_count}</p>
                </div>
                <div>
                  <p className="eyebrow">Last seen</p>
                  <p className="mt-1">{timeAgo(selected.last_detected_at)}</p>
                </div>
              </div>

              <div>
                <p className="eyebrow mb-1.5">{t("common.evidence")}</p>
                <pre className="mono max-h-[260px] overflow-auto rounded-md border border-[var(--line)] bg-[var(--surface-2)] p-3 text-[10.5px] leading-relaxed">
                  {JSON.stringify(payload, null, 2)}
                </pre>
              </div>

              {can("exception:triage") ? (
                <div className="space-y-2 border-t border-[var(--line)] pt-3">
                  <Input
                    placeholder="Resolution note (required when resolving)"
                    value={actionNote}
                    onChange={(event) => setActionNote(event.target.value)}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={triage.isPending}
                      onClick={() => triage.mutate({ id: selected.id, status: "ACKNOWLEDGED" })}
                    >
                      {t("exceptions.acknowledge")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={triage.isPending}
                      onClick={() => triage.mutate({ id: selected.id, status: "IGNORED", note: actionNote || undefined })}
                    >
                      {t("exceptions.ignore")}
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      loading={triage.isPending}
                      onClick={() => triage.mutate({ id: selected.id, status: "RESOLVED", note: actionNote })}
                    >
                      {t("exceptions.resolve")}
                    </Button>
                    {selected.case_id ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => (window.location.href = `/cases/${selected.case_id}`)}
                      >
                        Open case
                      </Button>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </DialogContent>
        ) : null}
      </Dialog>
    </>
  );
}

// Kept for type-completeness of shared imports in older builds.

