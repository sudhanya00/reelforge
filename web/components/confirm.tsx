"use client";

import * as React from "react";
import { Coins, Trash2 } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/primitives";
import { usd } from "@/lib/utils";

/** Spends at or above this ask first; smaller ones just go (the button already shows the cost). */
const CONFIRM_ABOVE_USD = 1;

type Ask = { title: string; usd: number; detail?: string; action?: string };
/** A non-spending confirmation, e.g. deleting a film. */
type Plain = { title: string; detail: string; action: string; destructive?: boolean };
const Ctx = React.createContext<(a: Ask) => Promise<boolean>>(async () => true);
const PlainCtx = React.createContext<(a: Plain) => Promise<boolean>>(async () => true);

export function ConfirmSpendProvider({ children }: { children: React.ReactNode }) {
  const [ask, setAsk] = React.useState<(Ask & { resolve: (ok: boolean) => void }) | null>(null);
  const [plain, setPlain] = React.useState<(Plain & { resolve: (ok: boolean) => void }) | null>(null);
  const confirmPlain = React.useCallback((a: Plain) => new Promise<boolean>((resolve) => setPlain({ ...a, resolve })), []);
  const closePlain = (ok: boolean) => {
    plain?.resolve(ok);
    setPlain(null);
  };

  const confirm = React.useCallback(
    (a: Ask) =>
      a.usd < CONFIRM_ABOVE_USD
        ? Promise.resolve(true)
        : new Promise<boolean>((resolve) => setAsk({ ...a, resolve })),
    [],
  );

  const close = (ok: boolean) => {
    ask?.resolve(ok);
    setAsk(null);
  };

  return (
    <Ctx.Provider value={confirm}>
     <PlainCtx.Provider value={confirmPlain}>
      {children}
      <Dialog open={!!plain} onOpenChange={(o) => !o && closePlain(false)}>
        <DialogContent hideClose className="max-w-sm">
          {plain?.destructive && (
            <div className="flex size-10 items-center justify-center rounded-full bg-destructive/12 text-destructive">
              <Trash2 className="size-5" />
            </div>
          )}
          <div className="space-y-1.5">
            <DialogTitle>{plain?.title}</DialogTitle>
            <DialogDescription>{plain?.detail}</DialogDescription>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" shape="pill" onClick={() => closePlain(false)}>
              Cancel
            </Button>
            <Button shape="pill" variant={plain?.destructive ? "destructive" : "default"} onClick={() => closePlain(true)}>
              {plain?.action}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={!!ask} onOpenChange={(o) => !o && close(false)}>
        <DialogContent hideClose className="max-w-sm">
          <div className="flex size-10 items-center justify-center rounded-full bg-live/15 text-live">
            <Coins className="size-5" />
          </div>
          <div className="space-y-1.5">
            <DialogTitle>{ask?.title}</DialogTitle>
            <DialogDescription>
              This will spend about <span className="font-semibold text-foreground">{usd(ask?.usd)}</span> of your
              credits.{ask?.detail ? ` ${ask.detail}` : ""}
            </DialogDescription>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" shape="pill" onClick={() => close(false)}>
              Cancel
            </Button>
            <Button shape="pill" autoFocus onClick={() => close(true)}>
              {ask?.action ?? "Generate"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
     </PlainCtx.Provider>
    </Ctx.Provider>
  );
}

export const useConfirmSpend = () => React.useContext(Ctx);
export const useConfirm = () => React.useContext(PlainCtx);
