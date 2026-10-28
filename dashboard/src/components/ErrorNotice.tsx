export function ErrorNotice({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-4 text-sm">
      {message}
    </div>
  );
}
