import { Spinner } from "@astryxdesign/core/Spinner";

export function Loading({ text }: { text: string }) {
  return (
    <div className="center-fill">
      <Spinner size="lg" label={text} />
    </div>
  );
}
