import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { formatDate, formatMoney, humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  PageHeader,
  Pagination,
  Select,
  Skeleton,
  StatusBadge,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { Page, PurchaseOrder, PurchaseOrderDetail } from "@/types/api";

const STATUSES = ["DRAFT", "OPEN", "PARTIALLY_RECEIVED", "COMPLETED", "CANCELLED", "EXPIRED"];

export function PurchaseOrdersPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");

  const params = { page, page_size: 25, search: search || undefined, status: status || undefined, sort: "issue_date", order: "desc" };
  const list = useQuery({
    queryKey: ["purchase-orders", params],
    queryFn: () => api.get<Page<PurchaseOrder>>(`/purchase-orders${buildQuery(params)}`),
  });

  const columns: Column<PurchaseOrder>[] = [
    {
      key: "po",
      header: t("po.number"),
      render: (row) => (
        <div>
          <div className="mono text-[11.5px] font-semibold">{row.po_number}</div>
          <div className="text-[11px] text-[var(--muted)]">{row.vendor_name}</div>
        </div>
      ),
    },
    { key: "issue", header: t("po.issueDate"), render: (row) => <span className="num text-[11.5px]">{formatDate(row.issue_date)}</span> },
    { key: "expiration", header: t("po.expiration"), render: (row) => <span className="num text-[11.5px]">{row.expiration_date ? formatDate(row.expiration_date) : "—"}</span> },
    { key: "total", header: t("common.total"), align: "right", render: (row) => <span className="num font-semibold">{formatMoney(row.total, row.currency)}</span> },
    { key: "invoiced", header: t("po.invoiced"), align: "right", render: (row) => <span className="num">{formatMoney(row.invoiced_amount, row.currency)}</span> },
    { key: "invoices", header: t("common.invoice"), align: "right", render: (row) => <span className="num">{row.invoice_count}</span> },
    { key: "status", header: t("common.status"), render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <>
      <PageHeader title={t("po.title")} subtitle={t("po.subtitle")} />
      <Card>
        <div className="toolbar">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--muted)]" />
            <Input className="pl-8" placeholder={t("common.search")} value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
          </div>
          <Select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} className="w-auto">
            <option value="">All statuses</option>
            {STATUSES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </Select>
        </div>
        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/purchase-orders/${row.id}`)}
          empty={<EmptyState title="No purchase orders" body="Create purchase orders or import them from your ERP." />}
        />
        {list.data ? <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} pageSize={list.data.meta.page_size} onPage={setPage} /> : null}
      </Card>
    </>
  );
}

export function PurchaseOrderDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["purchase-order", id],
    queryFn: () => api.get<PurchaseOrderDetail>(`/purchase-orders/${id}`),
  });

  const changeStatus = useMutation({
    mutationFn: (status: string) => api.post(`/purchase-orders/${id}/transition`, { status }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["purchase-order", id] });
      toast.success("Purchase order updated");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (detail.isError) return <Card><ErrorState message={(detail.error as Error).message} onRetry={() => detail.refetch()} /></Card>;
  const po = detail.data;

  const remaining = po ? Number(po.total) - Number(po.invoiced_amount) : 0;

  return (
    <>
      <button className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)] hover:text-[var(--ink)]" onClick={() => navigate("/purchase-orders")}>
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("po.title")}
      </button>
      {detail.isLoading || !po ? <Skeleton className="h-56" /> : (
        <>
          <PageHeader
            title={po.po_number}
            subtitle={`${po.vendor_name ?? "Vendor"} · issued ${formatDate(po.issue_date)}`}
            actions={
              can("po:update") ? (
                <Select
                  className="w-auto"
                  value={po.status}
                  onChange={(event) => changeStatus.mutate(event.target.value)}
                  disabled={changeStatus.isPending}
                >
                  {STATUSES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
                </Select>
              ) : undefined
            }
          >
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={po.status} />
              <Badge tone="neutral">{po.currency}</Badge>
              {po.is_demo ? <Badge tone="neutral">demo</Badge> : null}
              {po.expiration_date ? <Badge tone={new Date(po.expiration_date) < new Date() ? "danger" : "neutral"}>expires {formatDate(po.expiration_date)}</Badge> : null}
            </div>
          </PageHeader>

          <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
            <Card>
              <CardHeader title={t("po.lineItems")} />
              <table className="table">
                <thead><tr><th>#</th><th>{t("common.description")}</th><th className="text-right">{t("common.quantity")}</th><th className="text-right">{t("common.unitPrice")}</th><th className="text-right">{t("common.tax")} %</th><th className="text-right">{t("common.lineTotal")}</th></tr></thead>
                <tbody>
                  {po.items.map((item) => (
                    <tr key={item.id}>
                      <td className="num">{item.line_number}</td>
                      <td>{item.description}</td>
                      <td className="num text-right">{item.quantity}</td>
                      <td className="num text-right">{formatMoney(item.unit_price, po.currency)}</td>
                      <td className="num text-right">{item.tax_rate}</td>
                      <td className="num text-right font-semibold">{formatMoney(item.line_total, po.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader title="Financial position" />
                <CardBody className="space-y-2 text-[12px]">
                  <div className="flex justify-between"><span className="text-[var(--muted)]">{t("common.subtotal")}</span><span className="num">{formatMoney(po.subtotal, po.currency)}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--muted)]">{t("common.tax")}</span><span className="num">{formatMoney(po.tax, po.currency)}</span></div>
                  <div className="flex justify-between border-t border-[var(--line)] pt-1.5 font-semibold"><span>{t("common.total")}</span><span className="num">{formatMoney(po.total, po.currency)}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--muted)]">{t("po.invoiced")}</span><span className="num">{formatMoney(po.invoiced_amount, po.currency)}</span></div>
                  <div className="flex justify-between"><span className="text-[var(--muted)]">{t("po.remaining")}</span><span className="num">{formatMoney(remaining, po.currency)}</span></div>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title={t("po.linkedInvoices")} />
                <CardBody className="space-y-1.5 pt-3">
                  {po.invoices.map((invoice) => (
                    <Link key={String(invoice.id)} to={`/invoices/${invoice.id}`} className="flex items-center justify-between rounded border border-[var(--line)] px-2.5 py-2 text-[12px] hover:bg-[var(--surface-2)]">
                      <span className="mono">{String(invoice.invoice_number)}</span>
                      <div className="flex items-center gap-2"><span className="num">{formatMoney(String(invoice.total), String(invoice.currency))}</span><StatusBadge status={String(invoice.status)} /></div>
                    </Link>
                  ))}
                  {po.invoices.length === 0 ? <p className="text-[12px] text-[var(--muted)]">No invoices linked.</p> : null}
                </CardBody>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
