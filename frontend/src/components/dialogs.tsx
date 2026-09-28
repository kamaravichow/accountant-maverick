import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { HStack } from "@astryxdesign/core/Stack";
import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useToast } from "@astryxdesign/core/Toast";

// Promise-based replacements for window.prompt / confirm / alert, rendered with Astryx dialogs and toasts.

type PromptOpts = { title: string; label: string; initial?: string; description?: string; actionLabel?: string };
type ConfirmOpts = { title: string; description: string; actionLabel: string };
type Api = {
  prompt: (o: PromptOpts) => Promise<string | null>;
  confirm: (o: ConfirmOpts) => Promise<boolean>;
  notify: (message: string, type?: "info" | "error") => void;
};

const Ctx = createContext<Api | null>(null);

export function useDialogs(): Api {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDialogs must be used inside <DialogProvider>");
  return v;
}

export function DialogProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [prompt, setPrompt] = useState<(PromptOpts & { value: string }) | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOpts | null>(null);
  const resolvePrompt = useRef<(v: string | null) => void>(() => undefined);
  const resolveConfirm = useRef<(v: boolean) => void>(() => undefined);

  const api: Api = {
    prompt: useCallback(
      (o: PromptOpts) =>
        new Promise<string | null>((res) => {
          resolvePrompt.current = res;
          setPrompt({ ...o, value: o.initial ?? "" });
        }),
      [],
    ),
    confirm: useCallback(
      (o: ConfirmOpts) =>
        new Promise<boolean>((res) => {
          resolveConfirm.current = res;
          setConfirm(o);
        }),
      [],
    ),
    notify: useCallback((message: string, type: "info" | "error" = "info") => toast({ body: message, type }), [toast]),
  };

  const closePrompt = (v: string | null) => {
    resolvePrompt.current(v);
    setPrompt(null);
  };
  const closeConfirm = (v: boolean) => {
    resolveConfirm.current(v);
    setConfirm(null);
  };

  return (
    <Ctx.Provider value={api}>
      {children}
      <Dialog isOpen={!!prompt} onOpenChange={(o) => !o && closePrompt(null)} purpose="form" width={440}>
        {prompt && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (prompt.value.trim()) closePrompt(prompt.value.trim());
            }}
          >
            <Layout
              header={<DialogHeader title={prompt.title} subtitle={prompt.description} onOpenChange={() => closePrompt(null)} />}
              content={
                <LayoutContent>
                  <TextInput label={prompt.label} value={prompt.value} onChange={(v) => setPrompt({ ...prompt, value: v })} hasAutoFocus width="100%" />
                </LayoutContent>
              }
              footer={
                <LayoutFooter>
                  <HStack gap={2} justify="end">
                    <Button label="Cancel" variant="ghost" onClick={() => closePrompt(null)} />
                    <Button label={prompt.actionLabel ?? "OK"} variant="primary" type="submit" isDisabled={!prompt.value.trim()} />
                  </HStack>
                </LayoutFooter>
              }
            />
          </form>
        )}
      </Dialog>
      <AlertDialog
        isOpen={!!confirm}
        onOpenChange={(o) => !o && closeConfirm(false)}
        title={confirm?.title ?? ""}
        description={confirm?.description ?? ""}
        actionLabel={confirm?.actionLabel ?? "Confirm"}
        onAction={() => closeConfirm(true)}
      />
    </Ctx.Provider>
  );
}
