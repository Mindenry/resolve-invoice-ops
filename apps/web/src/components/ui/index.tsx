import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Inbox, Loader2, X } from "lucide-react";
import {
  cloneElement,
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { cn } from "@/lib/utils";
import { humanize, initials } from "@/lib/format";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-[7px] text-[13px] font-semibold transition-colors disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--accent)] text-[var(--on-accent)] hover:bg-[var(--accent-strong)] border border-transparent",
        secondary:
          "bg-[var(--surface)] text-[var(--ink)] border border-[var(--line-strong)] hover:bg-[var(--surface-3)]",
        ghost: "bg-transparent text-[var(--ink-soft)] hover:bg-[var(--surface-3)] hover:text-[var(--ink)]",
        danger: "bg-[var(--danger)] text-white hover:opacity-90 border border-transparent",
        outline:
          "border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent-soft)] bg-transparent",
      },
      size: {
        sm: "h-7 px-2.5 text-[12px]",
        md: "h-8.5 px-3.5",
        lg: "h-10 px-5 text-sm",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        {children}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("card-header", className)}>
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold leading-tight">{title}</h3>
        {description ? <p className="mt-0.5 text-xs text-[var(--muted)]">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card-body", className)} {...props} />;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn("input", className)} {...props} />,
);
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => <textarea ref={ref} className={cn("textarea", className)} {...props} />,
);
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select ref={ref} className={cn("select", className)} {...props}>
      {children}
    </select>
  ),
);
Select.displayName = "Select";

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: string }) {
  return (
    <label className="label" htmlFor={htmlFor}>
      {children}
      {hint ? <span className="ml-1 font-normal text-[var(--muted)]">({hint})</span> : null}
    </label>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  // Associate the control with its label for screen readers and test queries.
  const labelled =
    isValidElement(children) && !(children.props as { "aria-label"?: string })["aria-label"]
      ? cloneElement(children as ReactElement<Record<string, unknown>>, { "aria-label": label })
      : children;
  return (
    <div>
      <Label hint={hint}>{label}</Label>
      {labelled}
      {error ? <p className="mt-1 text-[11.5px] text-[var(--danger)]">{error}</p> : null}
    </div>
  );
}

export type Tone = "neutral" | "accent" | "danger" | "warning" | "info" | "success";

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span className={cn("badge", className)} data-tone={tone}>
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, Tone> = {
  OPEN: "info",
  INVESTIGATING: "info",
  AWAITING_INFORMATION: "warning",
  AWAITING_APPROVAL: "warning",
  RESOLUTION_IN_PROGRESS: "accent",
  RESOLVED: "success",
  REOPENED: "warning",
  CLOSED: "neutral",
  CANCELLED: "neutral",
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "danger",
  EXPIRED: "neutral",
  COMPLETED: "success",
  FAILED: "danger",
  RUNNING: "info",
  QUEUED: "neutral",
  EXECUTING: "info",
  PROPOSED: "neutral",
  VALIDATED: "info",
  AWAITING_APPROVAL_RES: "warning",
  INDEXED: "success",
  EXTRACTED: "accent",
  PROCESSING: "info",
  UPLOADED: "neutral",
  REQUIRES_REVIEW: "warning",
  SENT: "success",
  SKIPPED: "neutral",
  CONNECTED: "success",
  DEGRADED: "warning",
  DISCONNECTED: "danger",
  UNTESTED: "neutral",
  DISABLED: "neutral",
  READY_FOR_EXPORT: "success",
  MATCHED: "accent",
  DRAFT: "neutral",
  RECEIVED: "info",
  PARTIALLY_RECEIVED: "warning",
  ACTIVE: "success",
  INACTIVE: "neutral",
  BLOCKED: "danger",
  SUCCEEDED: "success",
  RETRYING: "warning",
};

export function StatusBadge({ status, label }: { status?: string | null; label?: string }) {
  if (!status) return <span className="text-[var(--muted)]">—</span>;
  const tone = STATUS_TONES[status] ?? "neutral";
  return <Badge tone={tone}>{label ?? humanize(status)}</Badge>;
}

export function SeverityBadge({ severity }: { severity?: string | null }) {
  const tone: Tone =
    severity === "CRITICAL" ? "danger" : severity === "HIGH" ? "warning" : severity === "MEDIUM" ? "info" : "neutral";
  return <Badge tone={tone}>{humanize(severity)}</Badge>;
}

export function PriorityBadge({ priority }: { priority?: string | null }) {
  const tone: Tone =
    priority === "URGENT" ? "danger" : priority === "HIGH" ? "warning" : priority === "MEDIUM" ? "info" : "neutral";
  return <Badge tone={tone}>{humanize(priority)}</Badge>;
}

export function RiskBadge({ risk }: { risk?: string | null }) {
  const tone: Tone =
    risk === "CRITICAL" || risk === "HIGH" ? "danger" : risk === "MEDIUM" ? "warning" : "neutral";
  return <Badge tone={tone}>{humanize(risk)}</Badge>;
}

export function Avatar({ name, color, size = 26 }: { name?: string | null; color?: string | null; size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full text-[10.5px] font-bold text-white"
      style={{ width: size, height: size, background: color || "var(--accent)" }}
      title={name ?? undefined}
    >
      {initials(name)}
    </span>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[22px] font-semibold leading-tight">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-2xl text-[13px] text-[var(--muted)]">{subtitle}</p> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  action,
  icon,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--surface-3)] text-[var(--muted)]">
        {icon ?? <Inbox className="h-5 w-5" />}
      </div>
      <p className="text-[14px] font-semibold text-[var(--ink)]">{title}</p>
      {body ? <p className="max-w-md text-[12.5px]">{body}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="empty">
      <AlertTriangle className="h-6 w-6 text-[var(--danger)]" />
      <p className="text-[14px] font-semibold text-[var(--ink)]">Something went wrong</p>
      <p className="max-w-md text-[12.5px]">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4 w-full", className)} />;
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-8" />
      ))}
    </div>
  );
}

export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--line)] px-4 py-2.5 text-[12px] text-[var(--muted)]">
      <span className="num">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="num px-2">
          {page} / {Math.max(pages, 1)}
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Next page"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-[var(--muted)]", className)} />;
}

export function InlineCheck({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--muted)]">
      <Check className="h-3.5 w-3.5 text-[var(--success)]" />
      {children}
    </span>
  );
}

export function Tabs({
  defaultValue,
  value,
  onValueChange,
  children,
  className,
}: {
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <TabsPrimitive.Root defaultValue={defaultValue} value={value} onValueChange={onValueChange} className={className}>
      {children}
    </TabsPrimitive.Root>
  );
}

export function TabsList({ children }: { children: ReactNode }) {
  return (
    <TabsPrimitive.List className="flex flex-wrap gap-1 border-b border-[var(--line)] px-1">
      {children}
    </TabsPrimitive.List>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className="-mb-px border-b-2 border-transparent px-3 py-2.5 text-[12.5px] font-semibold text-[var(--muted)] outline-none transition-colors hover:text-[var(--ink)] data-[state=active]:border-[var(--accent)] data-[state=active]:text-[var(--ink)]"
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ value, children, className }: { value: string; children: ReactNode; className?: string }) {
  return (
    <TabsPrimitive.Content value={value} className={cn("pt-4 outline-none", className)}>
      {children}
    </TabsPrimitive.Content>
  );
}

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  children,
  title,
  description,
  wide,
}: {
  children: ReactNode;
  title: string;
  description?: string;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-[1px] data-[state=open]:animate-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[88vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[10px] border border-[var(--line)] bg-[var(--surface)] p-5 shadow-[var(--shadow-md)]",
          wide ? "max-w-3xl" : "max-w-lg",
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <DialogPrimitive.Title className="text-[16px] font-semibold">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-1 text-[12.5px] text-[var(--muted)]">
                {description}
              </DialogPrimitive.Description>
            ) : null}
          </div>
          <DialogPrimitive.Close className="rounded p-1 text-[var(--muted)] hover:bg-[var(--surface-3)] hover:text-[var(--ink)]">
            <X className="h-4 w-4" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  danger,
  loading,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description={description}>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function KpiCard({
  label,
  value,
  detail,
  delta,
  unit,
}: {
  label: string;
  value: string;
  detail?: string | null;
  delta?: number | null;
  unit?: string;
}) {
  return (
    <div className="card kpi">
      <span className="eyebrow">{label}</span>
      <div className="flex items-end justify-between gap-2">
        <div className="kpi-value">
          {value}
          {unit && unit !== "count" ? (
            <span className="ml-1 text-[12px] font-medium text-[var(--muted)]">{unit}</span>
          ) : null}
        </div>
        {delta !== null && delta !== undefined ? (
          <span
            className={cn(
              "num mb-1 rounded px-1.5 py-0.5 text-[11px] font-semibold",
              delta >= 0
                ? "bg-[var(--success-soft)] text-[var(--success)]"
                : "bg-[var(--danger-soft)] text-[var(--danger)]",
            )}
          >
            {delta >= 0 ? "+" : ""}
            {delta.toFixed(1)}%
          </span>
        ) : null}
      </div>
      {detail ? <p className="line-clamp-2 text-[11.5px] leading-snug text-[var(--muted)]">{detail}</p> : null}
    </div>
  );
}
