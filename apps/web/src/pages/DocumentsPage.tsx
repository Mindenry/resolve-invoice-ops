import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, ScanText, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { api, buildQuery, errorMessage } from "@/lib/api";
import { formatBytes, formatDate, humanize } from "@/lib/format";
import { useI18n } from "@/i18n";
import { useAuth } from "@/providers/auth";
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Pagination,
  Select,
  StatusBadge,
} from "@/components/ui";
import { DataTable, type Column } from "@/components/data-table";
import type { DocumentRecord, Page, Vendor } from "@/types/api";

const DOCUMENT_TYPES = ["INVOICE", "PURCHASE_ORDER", "CONTRACT", "POLICY", "SOP", "CASE_ATTACHMENT", "OTHER"];
const STATUSES = ["UPLOADED", "QUEUED", "PROCESSING", "EXTRACTED", "INDEXED", "FAILED", "REQUIRES_REVIEW"];

export function DocumentsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [review, setReview] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [documentType, setDocumentType] = useState("INVOICE");
  const [vendorId, setVendorId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const params = { page, page_size: 25, search: search || undefined, status: status || undefined, requires_review: review === "yes" ? true : review === "no" ? false : undefined, sort: "created_at" };

  const list = useQuery({
    queryKey: ["documents", params],
    queryFn: () => api.get<Page<DocumentRecord>>(`/documents${buildQuery(params)}`),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => ["QUEUED", "PROCESSING", "UPLOADED"].includes(item.status)) ? 4_000 : false,
  });

  const vendors = useQuery({
    queryKey: ["vendors", "options"],
    queryFn: () => api.get<Page<Vendor>>("/vendors?page_size=100"),
    enabled: uploadOpen,
  });

  const capabilities = useQuery({
    queryKey: ["documents", "capabilities"],
    queryFn: () => api.get<{ ocr_available: boolean; ocr_detail: string }>("/documents/capabilities"),
    staleTime: 300_000,
  });

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a file first.");
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", documentType);
      if (vendorId) form.append("vendor_id", vendorId);
      return api.upload<{ document: DocumentRecord }>("/documents", form);
    },
    onSuccess: (result) => {
      setUploadOpen(false);
      setFile(null);
      toast.success("Document uploaded and queued for processing");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      navigate(`/documents/${result.document.id}`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const columns: Column<DocumentRecord>[] = [
    {
      key: "file",
      header: "Document",
      render: (row) => (
        <div className="max-w-[360px]">
          <div className="flex items-center gap-1.5">
            <FileUp className="h-3.5 w-3.5 text-[var(--muted)]" />
            <span className="truncate font-semibold">{row.original_filename}</span>
            {row.is_demo ? <Badge tone="neutral">demo</Badge> : null}
          </div>
          <div className="text-[10.5px] text-[var(--muted)]">
            {formatBytes(row.size_bytes)} · {row.mime_type.split("/").pop()} · v{row.current_version}
          </div>
        </div>
      ),
    },
    {
      key: "type",
      header: t("common.type"),
      render: (row) => <span className="text-[12px]">{humanize(row.document_type)}</span>,
    },
    {
      key: "status",
      header: t("common.status"),
      render: (row) => (
        <div className="flex items-center gap-1.5">
          <StatusBadge status={row.status} />
          {row.requires_review ? <Badge tone="warning">review</Badge> : null}
        </div>
      ),
    },
    {
      key: "pages",
      header: t("common.pageCount"),
      align: "right",
      render: (row) => <span className="num text-[12px]">{row.page_count}</span>,
    },
    {
      key: "confidence",
      header: t("common.confidence"),
      align: "right",
      render: (row) => (
        <span className="num text-[12px]">
          {row.ocr_confidence === null || row.ocr_confidence === undefined ? "—" : `${Math.round(row.ocr_confidence * 100)}%`}
        </span>
      ),
    },
    {
      key: "created",
      header: t("common.uploaded"),
      render: (row) => <span className="text-[11.5px] text-[var(--muted)]">{formatDate(row.created_at, "dd MMM HH:mm")}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title={t("docs.title")}
        subtitle={t("docs.subtitle")}
        actions={
          can("document:upload") ? (
            <Button variant="primary" size="sm" onClick={() => setUploadOpen(true)}>
              <UploadCloud className="h-3.5 w-3.5" />
              {t("docs.upload")}
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="toolbar">
          <div className="relative min-w-[220px] flex-1">
            <Input
              placeholder={`${t("common.search")}…`}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
            />
          </div>
          <Select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }} className="w-auto">
            <option value="">All statuses</option>
            {STATUSES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
          </Select>
          <Select value={review} onChange={(event) => { setReview(event.target.value); setPage(1); }} className="w-auto">
            <option value="">Any review state</option>
            <option value="yes">Requires review</option>
            <option value="no">Reviewed</option>
          </Select>
          <span className="flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
            <ScanText className="h-3.5 w-3.5" />
            {capabilities.data?.ocr_available ? "OCR available" : "OCR unavailable"}
          </span>
        </div>

        <DataTable
          columns={columns}
          rows={list.data?.items}
          loading={list.isLoading}
          rowKey={(row) => row.id}
          onRowClick={(row) => navigate(`/documents/${row.id}`)}
          empty={<EmptyState title="No documents" body="Upload an invoice or contract to start the processing pipeline." />}
        />
        {list.data ? (
          <Pagination page={list.data.meta.page} pages={list.data.meta.pages} total={list.data.meta.total} pageSize={list.data.meta.page_size} onPage={setPage} />
        ) : null}
      </Card>

      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent title={t("docs.upload")} description={t("docs.supported")}>
          <div className="space-y-4">
            <div
              className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-[var(--line-strong)] bg-[var(--surface-2)] px-4 py-8 text-center"
              onClick={() => inputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (event.dataTransfer.files[0]) setFile(event.dataTransfer.files[0]);
              }}
            >
              <UploadCloud className="mb-2 h-6 w-6 text-[var(--muted)]" />
              <p className="text-[12.5px] font-semibold">{file ? file.name : t("docs.dropzone")}</p>
              <p className="text-[11px] text-[var(--muted)]">{file ? formatBytes(file.size) : t("docs.supported")}</p>
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg,.jpeg"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("docs.documentType")}>
                <Select value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
                  {DOCUMENT_TYPES.map((value) => <option key={value} value={value}>{humanize(value)}</option>)}
                </Select>
              </Field>
              <Field label={t("common.vendor")} hint={t("common.optional")}>
                <Select value={vendorId} onChange={(event) => setVendorId(event.target.value)}>
                  <option value="">—</option>
                  {(vendors.data?.items ?? []).map((vendor) => (
                    <option key={vendor.id} value={vendor.id}>{vendor.legal_name}</option>
                  ))}
                </Select>
              </Field>
            </div>
            {upload.isPending ? (
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]">
                <div className="h-full w-1/3 animate-pulse rounded-full bg-[var(--accent)]" />
              </div>
            ) : null}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setUploadOpen(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={upload.isPending} disabled={!file} onClick={() => upload.mutate()}>
                {t("common.upload")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
