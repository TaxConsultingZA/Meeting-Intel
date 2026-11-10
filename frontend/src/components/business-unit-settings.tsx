"use client";

import { useEffect, useRef, useState } from "react";
import { chooseBusinessUnit, getBusinessUnits, getMe } from "@/lib/api";
import type { BusinessUnit, RegisteredUser } from "@/lib/types";

export default function BusinessUnitSettings({ token }: { token: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [account, setAccount] = useState<RegisteredUser | null>(null);
  const [units, setUnits] = useState<BusinessUnit[] | null>(null);
  const [query, setQuery] = useState("");
  const [choice, setChoice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function loadUnits() {
    setError("");
    try { setUnits(await getBusinessUnits(token)); }
    catch { setError("Business Units could not be loaded. Try again."); }
  }

  useEffect(() => {
    let active = true;
    void getMe(token).then(me => {
      if (!active || !me) return;
      setAccount(me);
      if (me.business_unit_id === null) {
        dialog.current?.showModal();
        void loadUnits();
      }
    }).catch(() => {});
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function save() {
    if (account?.business_unit_id !== null) return;
    setBusy(true);
    setError("");
    try {
      setAccount(await chooseBusinessUnit(token, {
        business_unit_id: Number(choice),
        business_unit_version: account.business_unit_version,
      }));
      window.dispatchEvent(new Event("business-unit-updated"));
      dialog.current?.close();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const matches = units?.filter(unit => unit.name.toLowerCase().includes(query.toLowerCase().trim().replace(/\s+/g, " ")));
  return <>
    <button className="rounded border px-2 py-1 text-sm" type="button" onClick={async () => {
      setError("");
      dialog.current?.showModal();
      try {
        const me = await getMe(token);
        setAccount(me);
        if (me?.business_unit_id === null) await loadUnits();
      } catch { setError("Account could not be loaded. Close this dialog and try again."); }
    }}>Personal settings</button>
    <dialog ref={dialog} aria-labelledby="bu-title" className="m-auto w-[min(92vw,28rem)] rounded-xl bg-white p-5 text-slate-900 shadow-xl backdrop:bg-black/40">
      <h2 id="bu-title" className="text-lg font-semibold">Business Unit</h2>
      {account?.business_unit_id != null ? <>
        <p>{account.business_unit_name}</p>
        <p>Contact an administrator to change your Business Unit.</p>
      </> : account && <>
        <p>Choose your Business Unit. This will not change your meeting permissions.</p>
        {units === null ? <button type="button" onClick={() => void loadUnits()}>Load Business Units</button> : <>
          <label className="block">Search Business Units<input className="block w-full rounded border p-2" value={query} maxLength={100} disabled={busy} onChange={event => { setQuery(event.target.value); setChoice(""); }} /></label>
          <label className="block">Choose a Business Unit<select className="block w-full rounded border p-2" value={choice} disabled={busy} onChange={event => setChoice(event.target.value)}>
            <option value="">Select a Business Unit</option>
            {matches?.map(unit => <option key={unit.id} value={unit.id}>{unit.name}</option>)}
          </select></label>
          {!matches?.length && <p>{units.length ? "No matching Business Units." : "No Business Units are available yet."}</p>}
          <button className="mt-3 rounded bg-[#003366] px-3 py-1 text-white disabled:opacity-50" disabled={busy || !choice} onClick={() => void save()}>{busy ? "Saving..." : "Save Business Unit"}</button>
        </>}
      </>}
      {error && <p role="alert">{error}</p>}
      <button className="ml-3 mt-3 underline" type="button" onClick={() => dialog.current?.close()}>{account?.business_unit_id === null ? "Later" : "Close"}</button>
    </dialog>
  </>;
}
