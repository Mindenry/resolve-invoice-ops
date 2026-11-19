import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileText,
  PlusCircle,
  RefreshCw,
  ShieldAlert,
  UploadCloud,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, errorMessage, fetchBlob } from "@/lib/api";
import { confidence, formatBytes, formatDateTime, formatNumber, humanize, timeAgo } from "@/lib/format";
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
  ErrorState,
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
import type { DocumentDetail, ExtractedField } from "@/types/api";

const STEPS = ["UPLOADED", "QUEUED", "PROCESSING", "EXTRACTED", "INDEXED"];

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  const { t } = useI18n();
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [editing, setEditing] = useState<ExtractedField | null>(null);
  const [editValue, setEditValue] = useState("");
  const [reviewOpen, setReviewOpen] = useState<"APPROVE" | "REJECT" | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [approveLow, setApproveLow] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [versionNote, setVersionNote] = useState("");
  const versionInput = useRef<HTMLInputElement>(null);

  const detail = useQuery({
    queryKey: ["document", id],
    queryFn: () => api.get<DocumentDetail>(`/documents/${id}`),
    refetchInterval: (query) =>
      query.state.data && ["QUEUED", "PROCESSING", "UPLOADED"].includes(query.state.data.status) ? 2_500 : false,
  });

  const document = detail.data;
  const documentId = document?.id;
  const documentMime = document?.mime_type;
  const documentVersion = document?.current_version;

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    if (documentId && documentMime && (documentMime.includes("pdf") || documentMime.startsWith("image/"))) {
      fetchBlob(`/documents/${documentId}/download`)
        .then((blob) => {
          if (cancelled) return;
          url = URL.createObjectURL(blob);
          setPreviewUrl(url);
        })
        .catch(() => setPreviewUrl(null));
    }
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [documentId, documentMime, documentVersion]);

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["document", id] });

  const correct = useMutation({
    mutationFn: () =>
      api.patch(`/documents/${id}/fields/${editing?.id}`, { value: editValue, notes: "Corrected during review" }),
    onSuccess: () => {
      setEditing(null);
      invalidate();
      toast.success("Field corrected");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const review = useMutation({
    mutationFn: () =>
      api.post(`/documents/${id}/review`, {
        action: reviewOpen,
        note: reviewNote || undefined,
        approve_low_confidence_fields: approveLow,
      }),
    onSuccess: () => {
      setReviewOpen(null);
      setReviewNote("");
      invalidate();
      toast.success("Extraction reviewed");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const reprocess = useMutation({
    mutationFn: () => api.post(`/documents/${id}/reprocess`, { reason: "Operator requested reprocessing" }),
    onSuccess: () => {
      invalidate();
      toast.success("Document queued for reprocessing");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const createInvoice = useMutation({
    mutationFn: (vendorId?: string) => api.post<{ invoice_id: string }>(`/documents/${id}/create-invoice`, { vendor_id: vendorId || null }),
    onSuccess: (result) => {
      toast.success("Invoice created");
      navigate(`/invoices/${result.invoice_id}`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const uploadVersion = useMutation({
    mutationFn: async () => {
      if (!versionFile) throw new Error("Choose a file");
      const form = new FormData();
      form.append("file", versionFile);
      if (versionNote) form.append("note", versionNote);
      return api.upload(`/documents/${id}/versions`, form);
    },
    onSuccess: () => {
      setVersionOpen(false);
      setVersionFile(null);
      setVersionNote("");
      invalidate();
      toast.success("New version uploaded");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const download = async () => {
    try {
      const blob = await fetchBlob(`/documents/${id}/download`);
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = detail.data?.original_filename ?? "document";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const extraction = document?.extraction;
  const lowConfidence = useMemo(
    () => (extraction?.fields ?? []).filter((field) => field.confidence < 0.6 && field.review_status === "PENDING"),
    [extraction],
  );

  if (detail.isError) {
    return (
      <Card>
        <ErrorState message={(detail.error as Error).message} onRetry={() => detail.refetch()} />
      </Card>
    );
  }

  return (
    <>
      <button
        className="mb-3 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--muted)] hover:text-[var(--ink)]"
        onClick={() => navigate("/documents")}
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("docs.title")}
      </button>

      {detail.isLoading || !document ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <PageHeader
            title={document.original_filename}
            subtitle={`${humanize(document.document_type)} · ${formatBytes(document.size_bytes)} · uploaded ${timeAgo(document.created_at)}`}
            actions={
              <>
                <Button variant="secondary" size="sm" onClick={() => void download()}>
                  <Download className="h-3.5 w-3.5" />
                  {t("common.download")}
                </Button>
                {can("document:upload") ? (
                  <Button variant="secondary" size="sm" onClick={() => setVersionOpen(true)}>
                    <PlusCircle className="h-3.5 w-3.5" />
                    {t("docs.newVersion")}
                  </Button>
                ) : null}
                {can("document:review") ? (
                  <Button variant="secondary" size="sm" loading={reprocess.isPending} onClick={() => reprocess.mutate()}>
                    <RefreshCw className="h-3.5 w-3.5" />
                    {t("docs.reprocess")}
                  </Button>
                ) : null}
                {can("document:review") && extraction ? (
                  <Button variant="primary" size="sm" loading={createInvoice.isPending} onClick={() => createInvoice.mutate(undefined)}>
                    {t("docs.createInvoice")}
                  </Button>
                ) : null}
              </>
            }
          >
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StatusBadge status={document.status} />
              {STEPS.map((step) => (
                <span key={step} className="flex items-center gap-1 text-[10px] text-[var(--muted)]">
                  <span
                    className={cn(
                      "dot",
                      STEPS.indexOf(document.status) >= STEPS.indexOf(step) ? "text-[var(--accent)]" : "text-[var(--line-strong)]",
                    )}
                  />
                  {humanize(step)}
                </span>
              ))}
              {document.requires_review ? <Badge tone="warning">{t("docs.requiresReview")}</Badge> : null}
              {document.indexed_at ? <Badge tone="success">Search indexed</Badge> : null}
            </div>
          </PageHeader>

          {document.processing_error ? (
            <div className="mb-4 rounded-md border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3 py-2 text-[12px] text-[var(--danger)]">
              <span className="font-semibold">{t("docs.extractionError")}: </span>
              {document.processing_error}
            </div>
          ) : null}

          <div className="split-pane">
            <Card className="overflow-hidden">
              <CardHeader
                title="Source document"
                description={document.page_count ? `${document.page_count} page(s)` : "Preview"}
                actions={<Badge tone="neutral">{document.mime_type.split("/").pop()}</Badge>}
              />
              <div className="bg-[var(--surface-3)] p-3">
                {previewUrl && document.mime_type.includes("pdf") ? (
                  <iframe title="Document preview" src={previewUrl} className="h-[620px] w-full rounded border border-[var(--line)] bg-white" />
                ) : previewUrl && document.mime_type.startsWith("image/") ? (
                  <img src={previewUrl} alt="Document" className="mx-auto max-h-[620px] rounded border border-[var(--line)]" />
                ) : (
                  <div className="flex h-[300px] items-center justify-center text-[12px] text-[var(--muted)]">
                    Preview is not available for this file type.
                  </div>
                )}
              </div>
            </Card>

            <Card>
              <CardHeader
                title={t("docs.extraction")}
                description={
                  extraction
                    ? `${extraction.field_count} fields · ${confidence(extraction.avg_confidence)} average confidence`
                    : t("docs.noExtraction")
                }
                actions={
                  extraction ? (
                    <StatusBadge status={extraction.review_status} />
                  ) : null
                }
              />
              <CardBody className="p-0">
                {!extraction ? (
                  <EmptyState title={t("docs.noExtraction")} body="The extraction pipeline has not produced fields for this document yet." />
                ) : (
                  <Tabs defaultValue="fields">
                    <div className="px-3 pt-1">
                      <TabsList>
                        <TabsTrigger value="fields">Fields ({extraction.fields.length})</TabsTrigger>
                        <TabsTrigger value="text">{t("docs.ocrText")}</TabsTrigger>
                        <TabsTrigger value="meta">Metadata</TabsTrigger>
                      </TabsList>
                    </div>
                    <TabsContent value="fields" className="px-3 pb-4">
                      {lowConfidence.length ? (
                        <div className="mb-2 flex items-start gap-2 rounded border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-2.5 py-2 text-[11.5px] text-[var(--warning)]">
                          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          {lowConfidence.length} field(s) have confidence below 60% and need explicit confirmation.
                        </div>
                      ) : null}
                      <div className="divide-y divide-[var(--line)]">
                        {extraction.fields.map((field) => (
                          <div key={field.id} className="py-2">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="mono text-[10.5px] uppercase tracking-wide text-[var(--muted)]">
                                    {humanize(field.field_name)}
                                  </span>
                                  <Badge tone="neutral">{humanize(field.method)}</Badge>
                                  {field.review_status !== "PENDING" ? <Badge tone={field.review_status === "REJECTED" ? "danger" : "success"}>{humanize(field.review_status)}</Badge> : null}
                                </div>
                                <p className="text-[13px] font-semibold">{field.effective_value ?? "—"}</p>
                                {field.source_text ? (
                                  <p className="mono line-clamp-2 text-[10.5px] text-[var(--muted)]">
                                    p.{field.page_number ?? "?"} · “{field.source_text}”
                                  </p>
                                ) : null}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                <div className="w-[54px]">
                                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]">
                                    <div
                                      className={cn(
                                        "h-full rounded-full",
                                        field.confidence < 0.6 ? "bg-[var(--warning)]" : "bg-[var(--accent)]",
                                      )}
                                      style={{ width: `${Math.round(field.confidence * 100)}%` }}
                                    />
                                  </div>
                                  <p className="num mt-0.5 text-right text-[10px] text-[var(--muted)]">{confidence(field.confidence)}</p>
                                </div>
                                {can("document:review") ? (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => {
                                      setEditing(field);
                                      setEditValue(field.effective_value ?? "");
                                    }}
                                  >
                                    {t("common.edit")}
                                  </Button>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                      {can("document:review") ? (
                        <div className="mt-3 flex flex-wrap gap-2 border-t border-[var(--line)] pt-3">
                          <Button size="sm" variant="primary" onClick={() => setReviewOpen("APPROVE")}>
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            {t("docs.approveExtraction")}
                          </Button>
                          <Button size="sm" variant="secondary" onClick={() => setReviewOpen("REJECT")}>
                            {t("docs.rejectExtraction")}
                          </Button>
                        </div>
                      ) : null}
                    </TabsContent>
                    <TabsContent value="text" className="px-3 pb-4">
                      <div className="max-h-[520px] overflow-y-auto rounded border border-[var(--line)] bg-[var(--surface-2)] p-3">
                        {document.pages.map((page) => (
                          <div key={page.page_number} className="mb-4 last:mb-0">
                            <div className="mb-1 flex items-center gap-2">
                              <Badge tone="neutral">Page {page.page_number}</Badge>
                              {!page.has_text_layer ? <Badge tone="warning">OCR</Badge> : null}
                              {page.ocr_confidence !== null && page.ocr_confidence !== undefined ? (
                                <span className="num text-[10px] text-[var(--muted)]">conf {confidence(page.ocr_confidence)}</span>
                              ) : null}
                            </div>
                            <pre className="whitespace-pre-wrap font-sans text-[11.5px] leading-relaxed">{page.text || "No text extracted."}</pre>
                          </div>
                        ))}
                      </div>
                    </TabsContent>
                    <TabsContent value="meta" className="px-3 pb-4">
                      <dl className="space-y-1.5 text-[11.5px]">
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Provider</dt><dd>{extraction.provider}</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Model</dt><dd>{extraction.model ?? "—"}</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Prompt</dt><dd className="mono">{extraction.prompt_version ?? "—"}</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Avg. confidence</dt><dd>{confidence(extraction.avg_confidence)}</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">Chunks</dt><dd>{formatNumber(document.chunk_count)}</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">SHA-256</dt><dd className="mono text-[9.5px]">{document.sha256.slice(0, 24)}…</dd></div>
                        <div className="flex justify-between gap-3"><dt className="text-[var(--muted)]">OCR</dt><dd>{document.capabilities?.ocr_available ? "available" : "unavailable"}</dd></div>
                      </dl>
                      <div className="mt-3 border-t border-[var(--line)] pt-2">
                        <p className="eyebrow mb-1.5">Versions</p>
                        {document.versions.map((version) => (
                          <div key={version.id} className="flex items-center justify-between border-b border-[var(--line)] py-1.5 text-[11.5px] last:border-0">
                            <span>v{version.version} · {formatBytes(version.size_bytes)}</span>
                            <span className="text-[var(--muted)]">{formatDateTime(version.created_at)}</span>
                          </div>
                        ))}
                      </div>
                    </TabsContent>
                  </Tabs>
                )}
              </CardBody>
            </Card>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted)]">
            <FileText className="h-3.5 w-3.5" />
            Processing runs asynchronously. Status refreshes automatically.
          </div>
        </>
      )}

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent title={`${t("docs.editField")}: ${editing ? humanize(editing.field_name) : ""}`} description={t("docs.sourceEvidence")}>
          <div className="space-y-4">
            {editing?.source_text ? (
              <blockquote className="rounded border-l-2 border-[var(--line-strong)] bg-[var(--surface-2)] px-3 py-2 text-[11.5px] italic">
                “{editing.source_text}” — page {editing.page_number ?? "?"}
              </blockquote>
            ) : null}
            <Field label="Corrected value">
              <Input value={editValue} onChange={(event) => setEditValue(event.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setEditing(null)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={correct.isPending} onClick={() => correct.mutate()}>
                {t("common.save")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(reviewOpen)} onOpenChange={(open) => !open && setReviewOpen(null)}>
        <DialogContent
          title={reviewOpen === "APPROVE" ? t("docs.approveExtraction") : t("docs.rejectExtraction")}
          description={reviewOpen === "APPROVE" ? "Approved values are persisted and the audit trail records your decision." : "Rejected extractions require a reason and cannot be converted to invoices."}
        >
          <div className="space-y-4">
            {reviewOpen === "APPROVE" && lowConfidence.length > 0 ? (
              <label className="flex items-start gap-2 text-[12px]">
                <input type="checkbox" checked={approveLow} onChange={(event) => setApproveLow(event.target.checked)} className="mt-0.5" />
                <span>I have reviewed the {lowConfidence.length} low-confidence field(s) and accept them.</span>
              </label>
            ) : null}
            <Field label={reviewOpen === "REJECT" ? t("common.reason") : t("common.notes")} hint={reviewOpen === "REJECT" ? t("common.required") : t("common.optional")}>
              <Textarea rows={3} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setReviewOpen(null)}>{t("common.cancel")}</Button>
              <Button
                variant={reviewOpen === "REJECT" ? "danger" : "primary"}
                loading={review.isPending}
                disabled={reviewOpen === "REJECT" && reviewNote.trim().length < 2}
                onClick={() => review.mutate()}
              >
                {reviewOpen === "APPROVE" ? t("common.approve") : t("common.reject")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={versionOpen} onOpenChange={setVersionOpen}>
        <DialogContent title={t("docs.newVersion")} description="A new version replaces the file, clears pages and queues reprocessing. Version history is retained.">
          <div className="space-y-4">
            <div
              className="flex cursor-pointer flex-col items-center rounded-lg border border-dashed border-[var(--line-strong)] px-4 py-6 text-center"
              onClick={() => versionInput.current?.click()}
            >
              <UploadCloud className="mb-2 h-5 w-5 text-[var(--muted)]" />
              <p className="text-[12.5px] font-semibold">{versionFile ? versionFile.name : t("docs.dropzone")}</p>
              <input
                ref={versionInput}
                type="file"
                className="hidden"
                accept=".pdf,.docx,.xlsx,.csv,.txt,.png,.jpg,.jpeg"
                onChange={(event) => setVersionFile(event.target.files?.[0] ?? null)}
              />
            </div>
            <Field label={t("common.notes")} hint={t("common.optional")}>
              <Input value={versionNote} onChange={(event) => setVersionNote(event.target.value)} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setVersionOpen(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" loading={uploadVersion.isPending} disabled={!versionFile} onClick={() => uploadVersion.mutate()}>
                {t("common.upload")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
