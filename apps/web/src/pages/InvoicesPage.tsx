import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, buildQuery } from "@/lib/api";
import { formatDate, formatMoney, humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { Badge, Card, EmptyState, Input, PageHeader, Pagination, Select, StatusBadge } from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { Invoice, Page } from "@/types/api";

const STATUSES = ["DRAFT", "RECEIVED", "PROCESSING", "VALIDATED", "MATCHED", "APPROVED", "READY_FOR_EXPORT", "REQUIRES_REVIEW", "REJECTED", "CANCELLED"];
const VALIDATION = ["PENDING", "PASSED", "WARNING", "FAILED"];

export function InvoicesPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [validation, setValidation] = useState("");
  const [exceptionsOnly, setExceptionsOnly] = useState(false);

  const params = {
    page,
    page_size: 25,
    search: search || undefined,
    status: status || undefined,
    validation_status: validation || undefined,
    exceptions_only: exceptionsOnly || undefined,
    sort: "invoice_date",
    order: "desc",
  };

  const list = useQuery({
    queryKey: ["invoices", params],
    queryFn: () => api.get<Page<Invoice>>(`/invoices${buildQuery(params)}`),
  });

  const columns: Column<Invoice>[] = [
    {
      key: "number",
      header: t("invoices.number"),
      render: (row) => (
        <div>
          <div className="mono text-[11.5px] font-semibold">{row.invoice_number}</div>
          <div className="text-[11px] text-[var(--muted)]">{row.source}</div>
        </div>
      ),
    },
    {
      key: "vendor",
      header: t("common.vendor"),
      render: (row) => <span className="text-[12px]">{row.vendor?.legal_name ?? row.vendor_name_raw ?? "—"}</span>,
    },
    {
      key: "date",
      header: t("invoices.date"),
      render: (row) => <span className="num text-[11.5px]">{formatDate(row.invoice_date)}</span>,
    },
    {
      key: "total",
      header: t("common.total"),
      align: "right",
      render: (row) => <span className="num font-semibold">{formatMoney(row.total, row.currency)}</span>,
    },
    {
      key: "po",
      header: "PO",
      render: (row) => <span className="mono text-[11px]">{row.purchase_order_number ?? "—"}</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => <StatusBadge status={row.status} />,
    },
    {
      key: "validation",
      header: t("invoices.validation"),
      render: (row) => <StatusBadge status={row.validation_status} />,
    },
    {
      key: "exceptions",
      header: t("cases.exceptions"),
      align: "right",
      render: (row) =>
        row.open_exception_count ? (
          <Badge tone="warning">{row.open_exception_count}</Badge>
        ) : (
          <span className="text-[var(--muted)]">0</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader title={t("invoices.title")} subtitle={t("invoices.subtitle")} />
      <Card>
        <div className="toolbar">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <Input
              className="pl-8"
              placeholder={t("common.search")}
              value={search}
              onChange={(event) => { setSearch(event.target.value); setPage(1); }}
            />
          </div>
          <Select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} className="w-auto">
            <option value="">All statuses</option>
            {STATUSES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </Select>
          <Select value={validation} onChange={(event) => { setValidation(event.target.value); setPage(1); }} className="w-auto">
            <option value="">Any validation</option>
            {VALIDATION.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </Select>
          <label className="flex items-center gap-1.5 text-[12px]">
            <input type="checkbox" checked={exceptionsOnly} onChange={(event) => { setExceptionsOnly(event.target.checked); setPage(1); }} />
            {t("invoices.exceptionsOnly")}
          </label>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/invoices/${row.id}`)}
          empty={<EmptyState title="No invoices" body="Invoices created from documents or imports will appear here." />}
        />
        {list.data ? (
          <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} pageSize={list.data.meta.page_size} onPage={setPage} />
        ) : null}
      </Card>
    </>
  );
}
