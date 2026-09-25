"use client";

import * as React from "react";
import { Coins } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/primitives";
import { usd } from "@/lib/utils";

/** Spends at or above this ask first; smaller ones just go (the button already shows the cost). */
const CONFIRM_ABOVE_USD = 1;

type Ask = { title: string; usd: number; detail?: string; action?: string };
const Ctx = React.createContext<(a: Ask) => Promise<boolean>>(async () => true);

export function ConfirmSpendProvider({ children }: { children: React.ReactNode }) {
  const [ask, setAsk] = React.useState<(Ask & { resolve: (ok: boolean) => void }) | null>(null);

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
      {children}
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
    </Ctx.Provider>
  );
}

export const useConfirmSpend = () => React.useContext(Ctx);
