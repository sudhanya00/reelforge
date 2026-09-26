"use client";

import * as React from "react";
import { toast } from "sonner";
import { useSWRConfig } from "swr";
import { Package, Plus, RefreshCw, Scan, Shirt, Trash2, TriangleAlert, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Input, Label, LiveBars, Popover, PopoverContent, PopoverTrigger, Segmented, Textarea, Tip } from "@/components/ui/primitives";
import { useConfirm } from "@/components/confirm";
import { imageUsd, useAppState, useJobResult, useProducts } from "@/lib/hooks";
import { api, url, type Job, type Product, type ProductUse, type Setup } from "@/lib/api";
import { cn, usd } from "@/lib/utils";
import { PhotoDrop, type Photo } from "./PhotoDrop";

const KIND_LABEL: Record<string, string> = {
  clothing: "Clothing", accessory: "Accessory", beauty: "Beauty", tech: "Tech", food: "Food & drink", object: "Other",
};

// ---------------------------------------------------------------- the library section

export function ProductsSection() {
  const { data } = useProducts();
  const [editing, setEditing] = React.useState<Product | "new" | null>(null);
  const items = data?.products ?? [];
  return (
    <section className="mt-16">
      <div className="mb-5 flex items-baseline gap-3">
        <h2 className="text-sm font-semibold">Products</h2>
        <p className="text-xs text-muted-foreground">Things your creators wear or hold in videos: a top, a lipstick, a gadget.</p>
      </div>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4">
        <button
          onClick={() => setEditing("new")}
          className="flex aspect-square flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-sm text-muted-foreground hover:border-foreground/30 hover:bg-accent/40 hover:text-foreground"
        >
          <Plus className="size-5" />
          Add a product
        </button>
        {items.map((p) => (
          <button key={p.id} onClick={() => setEditing(p)} className="group overflow-hidden rounded-xl border bg-card text-left transition-all hover:-translate-y-0.5 hover:shadow-md">
            <ProductImage p={p} className="aspect-square" />
            <div className="p-2.5">
              <p className="truncate text-sm font-medium">{p.name}</p>
              <p className="truncate text-xs text-muted-foreground">{p.brand || KIND_LABEL[p.kind]}</p>
            </div>
          </button>
        ))}
      </div>
      <ProductDialog product={editing === "new" ? null : editing} open={!!editing} onOpenChange={(o) => !o && setEditing(null)} />
    </section>
  );
}

function ProductImage({ p, className }: { p: Product; className?: string }) {
  const src = p.packshot ?? p.photos[0];
  return (
    <div className={cn("relative overflow-hidden bg-muted", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {src && <img src={url(src)} alt="" className={cn("size-full object-cover", p.status === "generating" && "opacity-50")} />}
      {p.status === "generating" && (
        <span className="absolute inset-0 flex items-center justify-center text-live">
          <LiveBars />
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- add / edit

type Fields = { name: string; brand: string; kind: string; description: string; notes: string };
const EMPTY: Fields = { name: "", brand: "", kind: "object", description: "", notes: "" };

export function ProductDialog({
  product,
  open,
  onOpenChange,
  onCreated,
}: {
  product: Product | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCreated?: (p: Product) => void;
}) {
  const { data: state } = useAppState();
  const { data } = useProducts();
  const { mutate } = useSWRConfig();
  const confirm = useConfirm();
  const [f, setF] = React.useState<Fields>(EMPTY);
  const [photos, setPhotos] = React.useState<Photo[]>([]);
  const [describing, setDescribing] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const live = product ? data?.products.find((x) => x.id === product.id) ?? product : null;

  React.useEffect(() => {
    if (!open) return;
    setF(product ? { name: product.name, brand: product.brand, kind: product.kind, description: product.description, notes: product.notes } : EMPTY);
    setPhotos([]);
  }, [open, product]);

  const onDescribed = React.useCallback((j: Job) => {
    setDescribing(null);
    if (j.status !== "done") return void toast.error("Couldn't read the photos", { description: j.error ?? undefined });
    const got = (j.result?.fields ?? {}) as Partial<Fields>;
    setF((cur) => ({
      name: cur.name || got.name || "",
      brand: cur.brand || got.brand || "",
      kind: cur.kind !== "object" ? cur.kind : got.kind || "object",
      description: cur.description || got.description || "",
      notes: cur.notes,
    }));
  }, []);
  useJobResult(describing, onDescribed);

  const describe = async () => {
    try {
      const j = await api.describePhotos("product", photos.map((p) => p.token), product?.id);
      setDescribing(j.id);
      mutate("/api/jobs");
    } catch (e) {
      toast.error("Couldn't start", { description: (e as Error).message });
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      if (product) {
        await api.updateProduct(product.id, f);
        toast.success("Product saved");
      } else {
        const r = await api.createProduct({ ...f, photos: photos.map((p) => p.token) });
        toast.success(`${r.product.name} added`, { description: "Painting a clean product shot from your photos." });
        onCreated?.(r.product);
      }
      mutate("/api/products");
      mutate("/api/jobs");
      onOpenChange(false);
    } catch (e) {
      toast.error("Couldn't save", { description: (e as Error).message });
    }
    setSaving(false);
  };

  const remove = async () => {
    if (!product || !(await confirm({ title: `Delete ${product.name}?`, detail: "Its photos move to the Recycle Bin. Videos already shot keep it.", action: "Delete", destructive: true }))) return;
    await api.deleteProduct(product.id);
    mutate("/api/products");
    onOpenChange(false);
  };

  const canDescribe = product ? true : photos.length > 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(640px,calc(100vw-2rem))] max-w-none">
        <div>
          <DialogTitle>{product ? product.name : "Add a product"}</DialogTitle>
          <DialogDescription className="mt-1">
            Photos of the real item. A clean product shot is painted from them, and videos keep the exact item on screen.
          </DialogDescription>
        </div>

        {live ? (
          <div className="flex gap-3">
            <div className="relative">
              <ProductImage p={live} className="size-28 rounded-lg border" />
              {live.status !== "generating" && (
                <Tip content="Repaint the product shot">
                  <button
                    onClick={async () => (await api.repaintPackshot(live.id), mutate("/api/products"), mutate("/api/jobs"))}
                    className="absolute top-1 right-1 rounded-full bg-background/90 p-1"
                    aria-label="Repaint the product shot"
                  >
                    <RefreshCw className="size-3" />
                  </button>
                </Tip>
              )}
            </div>
            <div className="flex flex-wrap content-start gap-1.5">
              {live.photos.map((ph) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={ph} src={url(ph)} alt="" className="size-14 rounded-md border object-cover" />
              ))}
              {live.error && (
                <p className="flex w-full items-start gap-1 text-xs text-destructive">
                  <TriangleAlert className="mt-0.5 size-3.5" />
                  {live.error}
                </p>
              )}
            </div>
          </div>
        ) : (
          <PhotoDrop photos={photos} onChange={setPhotos} max={4} hint="1-4 clear photos: the front, the label or logo up close, and one being worn or held if you have it." />
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. satin lipstick" />
          </div>
          <div className="space-y-1.5">
            <Label>Brand</Label>
            <Input value={f.brand} onChange={(e) => setF({ ...f, brand: e.target.value })} placeholder="as printed on it" />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Kind</Label>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(KIND_LABEL).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setF({ ...f, kind: k })}
                  className={cn("rounded-full border px-2.5 py-1 text-xs", f.kind === k ? "border-foreground/30 bg-foreground text-background" : "text-muted-foreground hover:text-foreground")}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <div className="flex items-center">
              <Label>What it looks like</Label>
              <Button size="sm" variant="ghost" shape="pill" className="-my-1 ml-auto h-7 text-xs" onClick={describe} disabled={!canDescribe || !!describing}>
                {describing ? <LiveBars className="h-3" /> : <Scan />}
                Fill from photos
              </Button>
            </div>
            <Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="Colours, material, finish, shape; any printed words exactly" className="min-h-16" />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>What they can say about it</Label>
            <Textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} placeholder="Facts from the brand or your own experience: 12 shades, lasts all day, €18. The script only uses these." className="min-h-12" />
          </div>
        </div>

        <div className="flex items-center gap-2 border-t pt-4">
          {product && (
            <Button variant="ghost" size="sm" shape="pill" onClick={remove} className="hover:bg-destructive/10 hover:text-destructive">
              <Trash2 />
              Delete
            </Button>
          )}
          <span className="ml-auto text-xs text-muted-foreground">{!product && `Product shot ≈ ${usd(imageUsd(state?.settings, 1))}`}</span>
          <Button shape="pill" onClick={save} disabled={saving || !f.name.trim() || (!product && !photos.length)}>
            {product ? "Save" : "Add product"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- picking products for a video

export function ProductPicker({
  value,
  onChange,
  disabled,
}: {
  value: Setup["products"];
  onChange: (v: Setup["products"]) => void;
  disabled?: boolean;
}) {
  const { data } = useProducts();
  const [adding, setAdding] = React.useState(false);
  const all = data?.products ?? [];
  const chosen = value.map((v) => ({ ...v, p: all.find((x) => x.id === v.id) })).filter((x) => x.p);
  const toggle = (p: Product) =>
    onChange(value.some((v) => v.id === p.id) ? value.filter((v) => v.id !== p.id) : [...value, { id: p.id, use: p.use }].slice(-2));
  const setUse = (id: string, use: ProductUse) => onChange(value.map((v) => (v.id === id ? { ...v, use } : v)));

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chosen.map(({ id, use, p }) => (
        <span key={id} className="flex items-center gap-1.5 rounded-full border py-0.5 pr-1 pl-0.5 text-xs">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {(p!.packshot ?? p!.photos[0]) && <img src={url(p!.packshot ?? p!.photos[0])} alt="" className="size-6 rounded-full object-cover" />}
          <span className="max-w-32 truncate">{p!.name}</span>
          <Segmented<ProductUse>
            size="sm"
            value={use}
            onChange={(u) => setUse(id, u)}
            className="scale-90 [&>button]:h-6 [&>button]:px-2"
            options={[
              { value: "wear", label: <><Shirt />wear</> },
              { value: "hold", label: <><Package />hold</> },
            ]}
          />
          {!disabled && (
            <button onClick={() => onChange(value.filter((v) => v.id !== id))} className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Remove ${p!.name}`}>
              <X className="size-3" />
            </button>
          )}
        </span>
      ))}
      {!disabled && value.length < 2 && (
        <Popover>
          <PopoverTrigger asChild>
            <button className="flex items-center gap-1 rounded-full border border-dashed px-2.5 py-1 text-xs text-muted-foreground hover:border-foreground/30 hover:text-foreground">
              <Package className="size-3.5" />
              {chosen.length ? "Add another" : "Feature a product"}
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-80 p-2">
            <div className="max-h-72 space-y-0.5 overflow-y-auto scrollbar-thin">
              {all.map((p) => (
                <button key={p.id} onClick={() => toggle(p)} className={cn("flex w-full items-center gap-3 rounded-lg p-1.5 text-left hover:bg-accent", value.some((v) => v.id === p.id) && "bg-accent")}>
                  <ProductImage p={p} className="size-10 shrink-0 rounded-md" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium">{p.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">{p.brand || KIND_LABEL[p.kind]} · usually {p.use === "wear" ? "worn" : "held"}</span>
                  </span>
                </button>
              ))}
              <button onClick={() => setAdding(true)} className="flex w-full items-center gap-2 rounded-lg p-2 text-sm text-muted-foreground hover:bg-accent hover:text-foreground">
                <Plus className="size-4" />
                Add a product
              </button>
            </div>
          </PopoverContent>
        </Popover>
      )}
      <ProductDialog product={null} open={adding} onOpenChange={setAdding} onCreated={(p) => onChange([...value, { id: p.id, use: p.use }].slice(-2))} />
    </div>
  );
}
