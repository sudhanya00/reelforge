"use client";

import * as React from "react";
import { Dialog as D, Popover as P, Tooltip as T } from "radix-ui";
import { XIcon } from "@/components/icons";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------- badge

const badgeTones = {
  neutral: "bg-secondary text-secondary-foreground",
  outline: "border text-muted-foreground",
  live: "bg-live/15 text-live",
  ok: "bg-ok/15 text-ok",
  bad: "bg-destructive/12 text-destructive",
} as const;

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.ComponentProps<"span"> & { tone?: keyof typeof badgeTones }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap [&_svg]:size-3",
        badgeTones[tone],
        className,
      )}
      {...props}
    />
  );
}

// ---------------------------------------------------------------- inputs

export function Input({ className, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "flex h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-sm shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground dark:bg-input/30",
        "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(
          "flex field-sizing-content min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs transition-[color,box-shadow] outline-none placeholder:text-muted-foreground dark:bg-input/30",
          "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);

/** Text that looks like text until you click into it. */
export function InlineText({
  value,
  onChange,
  className,
  placeholder,
  multiline = true,
}: {
  value: string;
  onChange: (v: string) => void;
  className?: string;
  placeholder?: string;
  multiline?: boolean;
}) {
  const base =
    "w-full resize-none rounded-md border border-transparent bg-transparent px-2 py-1 -mx-2 outline-none transition-colors hover:border-border focus:border-ring focus:bg-background focus:ring-[3px] focus:ring-ring/30 field-sizing-content placeholder:text-muted-foreground/60";
  return multiline ? (
    <textarea value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cn(base, className)} rows={1} />
  ) : (
    <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={cn(base, className)} />
  );
}

export function Label({ className, ...props }: React.ComponentProps<"label">) {
  return <label className={cn("text-xs font-medium text-muted-foreground", className)} {...props} />;
}

export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "pointer-events-none inline-flex h-5 items-center rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

// ---------------------------------------------------------------- segmented control

export function Segmented<V extends string>({
  value,
  onChange,
  options,
  size = "default",
  className,
}: {
  value: V;
  onChange: (v: V) => void;
  options: { value: V; label: React.ReactNode; disabled?: boolean; title?: string }[];
  size?: "sm" | "default";
  className?: string;
}) {
  return (
    <div className={cn("inline-flex items-center rounded-full bg-muted p-0.5", className)} role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full font-medium transition-all disabled:opacity-40 [&_svg]:size-3.5",
            size === "sm" ? "h-7 px-2.5 text-xs" : "h-8 px-3.5 text-sm",
            o.value === value
              ? "bg-background text-foreground shadow-sm dark:bg-accent"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- tooltip

export function Tip({ content, children, side = "top" }: { content: React.ReactNode; children: React.ReactNode; side?: "top" | "bottom" | "left" | "right" }) {
  if (!content) return <>{children}</>;
  return (
    <T.Root delayDuration={250}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs text-background shadow-md animate-in fade-in-0 zoom-in-95"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

export const TooltipProvider = T.Provider;

// ---------------------------------------------------------------- popover

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;

export function PopoverContent({ className, align = "end", ...props }: React.ComponentProps<typeof P.Content>) {
  return (
    <P.Portal>
      <P.Content
        align={align}
        sideOffset={8}
        className={cn(
          "z-50 w-80 rounded-xl border bg-popover p-0 text-popover-foreground shadow-lg outline-none animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          className,
        )}
        {...props}
      />
    </P.Portal>
  );
}

// ---------------------------------------------------------------- dialog + sheet

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

export function DialogContent({
  className,
  children,
  side,
  hideClose,
  ...props
}: React.ComponentProps<typeof D.Content> & { side?: "right"; hideClose?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:animate-out data-[state=closed]:fade-out-0" />
      <D.Content
        className={cn(
          "fixed z-50 flex flex-col gap-4 border bg-popover text-popover-foreground shadow-2xl outline-none",
          side === "right"
            ? "inset-y-2 right-2 w-[min(560px,calc(100vw-1rem))] rounded-2xl p-6 data-[state=open]:animate-in data-[state=open]:slide-in-from-right-8 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-right-8"
            : "top-1/2 left-1/2 w-[min(520px,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-2xl p-6 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95",
          className,
        )}
        {...props}
      >
        {children}
        {!hideClose && (
          <D.Close className="absolute top-4 right-4 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <XIcon className="size-4" />
            <span className="sr-only">Close</span>
          </D.Close>
        )}
      </D.Content>
    </D.Portal>
  );
}

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof D.Title>) {
  return <D.Title className={cn("text-lg font-semibold tracking-tight", className)} {...props} />;
}

export function DialogDescription({ className, ...props }: React.ComponentProps<typeof D.Description>) {
  return <D.Description className={cn("text-sm text-muted-foreground", className)} {...props} />;
}

// ---------------------------------------------------------------- misc

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn("size-4 animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/** The animated bars from the reference's mic visualiser, used as a "working" indicator. */
export function LiveBars({ className, bars = 5 }: { className?: string; bars?: number }) {
  return (
    <span className={cn("inline-flex h-3.5 items-end gap-[2px]", className)} aria-hidden>
      {Array.from({ length: bars }).map((_, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-current"
          style={{ animation: `livebar 0.9s ${i * 0.12}s ease-in-out infinite alternate`, height: "30%" }}
        />
      ))}
      <style>{`@keyframes livebar{from{height:25%}to{height:100%}}`}</style>
    </span>
  );
}

/** Thin labelled progress bar, like the expression bars in the reference. */
export function Meter({ label, value, total, tone = "neutral" }: { label: string; value: number; total: number; tone?: "neutral" | "ok" | "live" }) {
  const pct = total ? Math.min(100, (value / total) * 100) : 0;
  const color = tone === "ok" ? "bg-ok" : tone === "live" ? "bg-live" : "bg-foreground/70";
  return (
    <div className="min-w-0 flex-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="truncate font-medium">{label}</span>
        <span className="tabular text-muted-foreground">
          {value}/{total}
        </span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-all duration-500", color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
