"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { chooseBusinessUnit, getBusinessUnits, getMe } from "@/lib/api";
import type { BusinessUnit, RegisteredUser } from "@/lib/types";

export const BUSINESS_UNIT_SNOOZE_MS = 5 * 60 * 1000;

function snoozeKey(upn: string) { return `meeting-intel:business-unit-snooze:${upn.toLowerCase()}`; }
function snoozedUntil(upn: string) { return Number(window.localStorage.getItem(snoozeKey(upn))) || 0; }

export default function BusinessUnitSettings({ token }: { token: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const listbox = useRef<HTMLDivElement>(null);
  const accountRef = useRef<RegisteredUser | null>(null);
  const reminderTimer = useRef<number | null>(null);
  const [account, setAccount] = useState<RegisteredUser | null>(null);
  const [units, setUnits] = useState<BusinessUnit[] | null>(null);
  const [query, setQuery] = useState("");
  const [choice, setChoice] = useState<BusinessUnit | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [listOpen, setListOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const listboxId = useId();

  const matches = useMemo(() => units?.filter(unit =>
    unit.name.toLowerCase().includes(query.toLowerCase().trim().replace(/\s+/g, " ")),
  ) ?? [], [query, units]);

  function focusDialog() { requestAnimationFrame(() => closeButton.current?.focus()); }
  function setCurrentAccount(next: RegisteredUser | null) { accountRef.current = next; setAccount(next); }
  function clearReminderTimer() {
    if (reminderTimer.current !== null) window.clearTimeout(reminderTimer.current);
    reminderTimer.current = null;
  }
  function scheduleReminder(until: number) {
    clearReminderTimer();
    reminderTimer.current = window.setTimeout(() => {
      reminderTimer.current = null;
      const currentAccount = accountRef.current;
      if (currentAccount?.business_unit_id === null && !dialog.current?.open) {
        dialog.current?.showModal(); void loadUnits(); focusDialog();
      }
    }, Math.max(0, until - Date.now()));
  }

  async function loadUnits() {
    setError("");
    try { setUnits(await getBusinessUnits(token)); }
    catch { setError("Business Units could not be loaded. Try again."); }
  }

  function closeDialog(snooze = false) {
    const currentAccount = accountRef.current ?? account;
    if (snooze && currentAccount?.business_unit_id === null) {
      const until = Date.now() + BUSINESS_UNIT_SNOOZE_MS;
      window.localStorage.setItem(snoozeKey(currentAccount.upn), String(until));
      scheduleReminder(until);
    }
    setListOpen(false);
    dialog.current?.close();
    window.setTimeout(() => trigger.current?.focus(), 0);
  }

  async function openDialog() {
    setError(""); setNotice(""); setQuery(""); setChoice(null); setActiveIndex(-1);
    try {
      const me = await getMe(token);
      setCurrentAccount(me);
      if (me?.business_unit_id === null) {
        dialog.current?.showModal();
        await loadUnits(); focusDialog();
      } else {
        setSettingsOpen(true);
      }
    } catch { setNotice("Account settings could not be loaded. Try again."); }
  }

  useEffect(() => {
    let active = true;
    void getMe(token).then(me => {
      if (!active || !me) return;
      setCurrentAccount(me);
      if (me.business_unit_id === null) {
        const until = snoozedUntil(me.upn);
        if (until > Date.now()) scheduleReminder(until);
        else { dialog.current?.showModal(); void loadUnits(); focusDialog(); }
      }
    }).catch(() => {});
    return () => { active = false; clearReminderTimer(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => { setActiveIndex(matches.length ? 0 : -1); }, [query, units]);

  useEffect(() => {
    if (!listOpen || activeIndex < 0) return;
    const option = listbox.current?.querySelector<HTMLElement>(`#${CSS.escape(`${listboxId}-${matches[activeIndex]?.id}`)}`);
    option?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, listOpen, listboxId, matches]);

  async function save() {
    if (!choice || account?.business_unit_id !== null) return;
    setBusy(true); setError("");
    try {
      const saved = await chooseBusinessUnit(token, { business_unit_id: choice.id, business_unit_version: account.business_unit_version });
      window.localStorage.removeItem(snoozeKey(saved.upn));
      clearReminderTimer();
      setCurrentAccount(saved);
      setNotice(`Business Unit saved: ${choice.name}.`);
      window.dispatchEvent(new Event("business-unit-updated"));
      closeDialog();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save your Business Unit. Try again.");
    } finally { setBusy(false); }
  }

  function choose(unit: BusinessUnit) {
    setChoice(unit); setQuery(unit.name); setListOpen(false); setError("");
  }

  function onSearchKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault(); setListOpen(true);
      setActiveIndex(index => Math.min(matches.length - 1, Math.max(0, index + 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault(); setListOpen(true); setActiveIndex(index => Math.max(0, index - 1));
    } else if (event.key === "Enter" && listOpen && activeIndex >= 0 && matches[activeIndex]) {
      event.preventDefault(); choose(matches[activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault(); if (listOpen) setListOpen(false); else closeDialog(true);
    }
  }

  return <>
    <button ref={trigger} aria-expanded={settingsOpen} className="rounded border border-white/50 px-2 py-1 text-sm text-white transition hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C9A52C]" type="button" onClick={() => void openDialog()}>Personal settings</button>
    {notice && <p className="sr-only" role="status">{notice}</p>}
    {settingsOpen && account?.business_unit_id != null && <div role="dialog" aria-label="Business Unit settings" className="absolute right-4 top-14 z-50 w-72 rounded-xl border border-slate-200 bg-white p-4 text-slate-900 shadow-xl">
      <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-[#003366]">Business Unit</p><p className="mt-1 text-sm text-slate-700">{account.business_unit_name}</p><p className="mt-2 text-xs text-slate-500">Contact an administrator to change it.</p></div><button type="button" aria-label="Close Business Unit settings" onClick={() => setSettingsOpen(false)} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xl text-[#003366] hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#C9A52C]">×</button></div>
    </div>}
    <dialog ref={dialog} aria-labelledby="bu-title" aria-describedby="bu-description" onCancel={event => { event.preventDefault(); closeDialog(true); }} onClose={() => { setListOpen(false); window.setTimeout(() => trigger.current?.focus(), 0); }} className="fixed inset-0 m-auto hidden h-[26rem] w-[min(92vw,30rem)] max-h-[calc(100dvh-1rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-[#f5f7fa] p-0 text-slate-900 shadow-2xl backdrop:bg-[#001f3f]/55 open:flex sm:max-h-[calc(100dvh-2rem)]">
      <div className="shrink-0 border-b border-slate-200 bg-[#003366] px-4 py-3 text-white sm:px-5">
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="bu-title" className="text-lg font-semibold">Choose your Business Unit</h2><p id="bu-description" className="mt-1 text-sm leading-5 text-white/80">This helps us group usage metrics. It does not change your meeting access.</p></div>
          <button ref={closeButton} type="button" aria-label="Close Business Unit dialog" onClick={() => closeDialog(true)} className="-mr-1 -mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xl text-white/85 transition hover:bg-white/15 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C9A52C]">×</button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4 sm:p-5">
        {account?.business_unit_id != null ? <><p className="font-medium text-[#003366]">{account.business_unit_name}</p><p className="mt-1 text-sm text-slate-600">Contact an administrator to change your Business Unit.</p></> : account && <div className="flex min-h-0 flex-1 flex-col">
          {units === null ? <button type="button" onClick={() => void loadUnits()} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-[#003366]">Load Business Units</button> : <>
            <label htmlFor="business-unit-search" className="text-sm font-medium text-[#003366]">Business Unit</label>
            <div className="relative mt-1.5 flex h-11 shrink-0 items-center rounded-xl border border-slate-300 bg-white shadow-sm transition focus-within:border-[#003366] focus-within:ring-2 focus-within:ring-[#C9A52C]/45">
              <input ref={searchInput} id="business-unit-search" role="combobox" aria-autocomplete="list" aria-controls={listboxId} aria-expanded={listOpen} aria-activedescendant={listOpen && activeIndex >= 0 ? `${listboxId}-${matches[activeIndex]?.id}` : undefined} aria-label="Search and choose a Business Unit" className="h-full min-w-0 flex-1 rounded-l-xl bg-transparent px-3 text-sm text-slate-900 outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:bg-slate-100" placeholder="Search Business Units" value={query} maxLength={100} disabled={busy} onFocus={() => setListOpen(true)} onChange={event => { setQuery(event.target.value); setChoice(null); setListOpen(true); }} onKeyDown={onSearchKeyDown} />
              <button type="button" aria-label={listOpen ? "Hide Business Units" : "Show Business Units"} aria-expanded={listOpen} aria-controls={listboxId} onMouseDown={event => event.preventDefault()} onClick={() => setListOpen(open => !open)} className="grid h-10 w-10 shrink-0 place-items-center rounded-r-xl text-[#003366] transition hover:text-[#001f3f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-[#C9A52C]"><ChevronDown aria-hidden="true" size={18} className={`transition-transform duration-150 ${listOpen ? "rotate-180" : ""}`} /></button>
            </div>
            <div className="mt-1.5 min-h-0 flex-1 overflow-hidden">
              {listOpen ? <div ref={listbox} id={listboxId} role="listbox" aria-label="Business Unit results" className="h-full max-h-52 overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-inner">
                {matches.length ? matches.map((unit, index) => <button type="button" id={`${listboxId}-${unit.id}`} role="option" aria-selected={choice?.id === unit.id} key={unit.id} onMouseDown={event => event.preventDefault()} onClick={() => choose(unit)} className={`block w-full rounded-lg px-3 py-2 text-left text-sm break-words ${index === activeIndex ? "bg-[#e8f0f7] text-[#003366]" : "text-slate-700 hover:bg-slate-100"} focus-visible:bg-[#e8f0f7] focus-visible:outline-none`}>{unit.name}</button>) : <p className="px-3 py-3 text-sm text-slate-600">No matching Business Units.</p>}
              </div> : error ? <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : choice ? <p className="pt-3 text-sm text-slate-600" role="status">Selected: <span className="font-medium text-[#003366]">{choice.name}</span></p> : <p className="pt-3 text-sm text-slate-500">Start typing or use the chevron to browse Business Units.</p>}
            </div>
            <div className="mt-3 flex shrink-0 justify-end gap-2"><button type="button" onClick={() => closeDialog(true)} disabled={busy} className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-[#003366] transition hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C9A52C] disabled:opacity-60">Later</button><button type="button" disabled={busy || !choice} onClick={() => void save()} className="rounded-lg bg-[#003366] px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-[#00284f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C9A52C] disabled:cursor-not-allowed disabled:bg-slate-400 disabled:text-white">{busy ? "Saving Business Unit…" : "Save Business Unit"}</button></div>
          </>}
        </div>}
      </div>
    </dialog>
  </>;
}
