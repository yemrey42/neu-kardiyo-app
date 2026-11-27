export function PageTitle({ title, desc }: { title: string; desc?: string }) {
  return (
    <div className="mb-8">
      <h1 className="text-3xl font-bold text-slate-900">{title}</h1>
      {desc && <p className="mt-2 max-w-3xl text-slate-600">{desc}</p>}
    </div>
  );
}
