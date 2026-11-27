"use client";

import { useActionState } from "react";
import { login, type LoginState } from "./actions";

export function LoginForm({ next = "/calismalar" }: { next?: string }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(login, null);
  return (
    <form action={action} className="max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <input type="hidden" name="next" value={next} />
      <label className="block text-sm font-medium">
        E-posta
        <input name="email" type="email" required defaultValue={state?.email} key={state?.email} autoComplete="email" className="mt-1 block w-full rounded border px-3 py-2" />
      </label>
      <label className="block text-sm font-medium">
        Şifre
        <input name="password" type="password" required autoComplete="current-password" className="mt-1 block w-full rounded border px-3 py-2" />
      </label>
      <button disabled={pending} className="w-full rounded bg-brand px-4 py-2 text-white disabled:opacity-60">
        {pending ? "Giriş yapılıyor..." : "Giriş"}
      </button>
      {state && !state.ok && <p className="text-sm text-red-700">{state.message}</p>}
      <p className="text-xs text-slate-500">Hesaplar yönetici tarafından açılır. Şifrenizi unuttuysanız yöneticiye başvurun.</p>
    </form>
  );
}
