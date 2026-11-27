"use client";

import { useActionState } from "react";
import { login, type SaveState } from "./actions";

export function LoginForm({ slug }: { slug: string }) {
  const [state, action, pending] = useActionState<SaveState, FormData>(login.bind(null, slug), null);
  return (
    <form action={action} className="max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-5">
      <label className="block text-sm font-medium">
        Veri girişi şifresi
        <input name="password" type="password" required className="mt-1 block w-full rounded border px-3 py-2" />
      </label>
      <button disabled={pending} className="rounded bg-brand px-4 py-2 text-white disabled:opacity-60">
        Giriş
      </button>
      {state && !state.ok && <p className="text-sm text-red-700">{state.message}</p>}
    </form>
  );
}
