import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, BellRing, Briefcase, CalendarDays, CalendarPlus, ChevronLeft, ChevronRight, ExternalLink, List, Radar } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { OwnerTag } from "../components/review";
import { Spinner, useToast } from "../components/ui";
import { api, download } from "../lib/api";
import { money } from "../lib/format";

type Ev = any;
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fromIso = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const longDay = (s: string) => fromIso(s).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const left = (n: number) => (n < 0 ? `${-n} day${n === -1 ? "" : "s"} overdue` : n === 0 ? "Today" : n === 1 ? "Tomorrow" : `In ${n} days`);
const leftTone = (n: number) => (n < 0 ? "text-fit-gap-ink font-semibold" : n <= 3 ? "text-ember-600 font-semibold" : "text-ink-muted");

function pref<T extends string>(key: string, def: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => { try { return (localStorage.getItem(key) as T) || def; } catch { return def; } });
  return [v, (x: T) => { setV(x); try { localStorage.setItem(key, x); } catch { /* ignore */ } }];
}

function Chip({ e }: { e: Ev }) {
  const deal = e.kind === "deal";
  return (
    <Link to={e.link} title={deal ? `${e.title}${e.client ? ` (${e.client})` : ""} · owner ${e.owner?.name || "not set"}` : `${e.title} · ${e.buyer || ""}`}
      className={clsx("block truncate rounded-[5px] px-1.5 py-[2px] text-[11.5px] font-medium leading-tight border",
        deal ? (e.closed ? "bg-paper border-line text-ink-muted line-through" : "bg-brand-800 border-brand-800 text-white")
          : e.saved ? "bg-ember-50 border-ember-400 text-ember-600" : "bg-white border-line text-ink-soft border-dashed")}>
      {deal ? <Briefcase className="inline h-3 w-3 -mt-px mr-1" /> : <Radar className="inline h-3 w-3 -mt-px mr-1" />}{e.title}
    </Link>
  );
}

function Month({ cursor, events, today }: { cursor: Date; events: Ev[]; today: string }) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - ((first.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  const weeks = days[35].getMonth() !== cursor.getMonth() ? 5 : 6;
  const by = useMemo(() => {
    const m: Record<string, Ev[]> = {};
    events.forEach((e) => (m[e.date] ||= []).push(e));
    Object.values(m).forEach((l) => l.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "deal" ? -1 : 1)));
    return m;
  }, [events]);
  const [more, setMore] = useState<string | null>(null);
  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-7 border-b border-line bg-paper">
        {WEEKDAYS.map((w) => <div key={w} className="px-2 py-2 text-[11.5px] font-semibold uppercase tracking-wide text-ink-muted">{w}</div>)}
      </div>
      <div className="grid grid-cols-7">
        {days.slice(0, weeks * 7).map((d) => {
          const k = iso(d);
          const list = by[k] || [];
          const out = d.getMonth() !== cursor.getMonth();
          const shown = more === k ? list : list.slice(0, 3);
          return (
            <div key={k} className={clsx("min-h-[112px] border-b border-r border-line-soft p-1.5 space-y-1", out && "bg-paper/60")}>
              <div className={clsx("text-[12px] num font-semibold h-6 w-6 grid place-items-center rounded-full", k === today ? "bg-ember-500 text-white" : out ? "text-ink-faint" : "text-ink-soft")}>{d.getDate()}</div>
              {shown.map((e) => <Chip key={e.kind + e.id} e={e} />)}
              {list.length > 3 && more !== k && <button className="text-[11.5px] text-brand-700 hover:underline px-1" onClick={() => setMore(k)}>+{list.length - 3} more</button>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Agenda({ events }: { events: Ev[] }) {
  const groups = useMemo(() => {
    const m = new Map<string, Ev[]>();
    [...events].sort((a, b) => a.date.localeCompare(b.date)).forEach((e) => m.set(e.date, [...(m.get(e.date) || []), e]));
    return [...m.entries()];
  }, [events]);
  if (!groups.length) return <div className="card p-8 text-center text-ink-muted text-[14px]">Nothing due in this period.</div>;
  return (
    <div className="card divide-y divide-line-soft">
      {groups.map(([day, list]) => (
        <div key={day} className="grid md:grid-cols-[150px_1fr] gap-2 px-5 py-3">
          <div><div className="font-semibold text-[13.5px]">{longDay(day)}</div><div className={clsx("text-[12px]", leftTone(list[0].days_left))}>{left(list[0].days_left)}</div></div>
          <div className="space-y-2">{list.map((e) => <Row key={e.kind + e.id} e={e} />)}</div>
        </div>
      ))}
    </div>
  );
}

function Row({ e, why }: { e: Ev; why?: string }) {
  if (e.kind === "deal") {
    return (
      <div className="flex items-start gap-3">
        <span className="mt-0.5 h-7 w-7 rounded-lg bg-brand-800 text-white grid place-items-center shrink-0"><Briefcase className="h-3.5 w-3.5" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><Link to={e.link} className="font-semibold text-[13.5px] hover:text-brand-700">{e.title}</Link><OwnerTag owner={e.owner} />
            {e.closed && <span className="chip bg-paper text-ink-muted capitalize">{e.status.replace("_", " ")}</span>}</div>
          <div className="text-[12.5px] text-ink-muted">{e.client ? `${e.client} · ` : ""}Submission due · {e.approved} of {e.stages} stages approved
            {e.open_notes > 0 && !why && <span className="text-ember-600"> · {e.open_notes} review note{e.open_notes > 1 ? "s" : ""} to fix</span>}</div>
          {why && <div className="text-[12.5px] text-ink-soft mt-0.5">{why}</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3">
      <span className={clsx("mt-0.5 h-7 w-7 rounded-lg grid place-items-center shrink-0 border", e.saved ? "bg-ember-50 border-ember-400 text-ember-600" : "bg-white border-line text-ink-muted")}><Radar className="h-3.5 w-3.5" /></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><Link to={e.link} className="font-semibold text-[13.5px] hover:text-brand-700 line-clamp-1">{e.title}</Link>
          <span className={clsx("chip", e.saved ? "bg-ember-50 text-ember-600" : "bg-paper text-ink-muted")}>{e.saved ? "Saved" : `Strong fit · ${e.score}`}</span></div>
        <div className="text-[12.5px] text-ink-muted">Tender closes · {e.buyer || "Buyer not stated"}{e.country ? `, ${e.country}` : ""}{e.value ? ` · ${money(e.value, e.currency)}` : ""}
          {e.url && <a href={e.url} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-0.5 text-brand-700 hover:underline">Notice <ExternalLink className="h-3 w-3" /></a>}</div>
        {why && <div className="text-[12.5px] text-ink-soft mt-0.5">{why}</div>}
      </div>
    </div>
  );
}

export default function CalendarPage() {
  const toast = useToast();
  const [cursor, setCursor] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });
  const [view, setView] = pref<"month" | "list">("rf-cal-view", "month");
  const [tenders, setTenders] = pref<"saved_strong" | "saved" | "none">("rf-cal-tenders", "saved_strong");
  const [hideClosed, setHideClosed] = pref<"1" | "0">("rf-cal-hide-closed", "1");
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const gridStart = new Date(first); gridStart.setDate(1 - ((first.getDay() + 6) % 7));
  const gridEnd = new Date(gridStart); gridEnd.setDate(gridStart.getDate() + 41);
  const range = view === "month" ? [iso(gridStart), iso(gridEnd)] : [iso(first), iso(new Date(cursor.getFullYear(), cursor.getMonth() + 3, 0))];
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["calendar", range[0], range[1], tenders],
    queryFn: () => api.get<any>(`/calendar?start=${range[0]}&end=${range[1]}&tenders=${tenders}`),
    placeholderData: (p) => p,
  });
  const events: Ev[] = (data?.events || []).filter((e: Ev) => hideClosed === "0" || !e.closed);
  const monthLabel = view === "month" ? cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })
    : `${cursor.toLocaleDateString(undefined, { month: "short", year: "numeric" })} – ${new Date(cursor.getFullYear(), cursor.getMonth() + 2, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" })}`;
  const move = (n: number) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + n, 1));
  const counts = { deals: events.filter((e) => e.kind === "deal").length, tenders: events.filter((e) => e.kind === "tender").length };

  return (
    <div className="px-4 lg:px-8 py-7 max-w-[1400px] space-y-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[260px]">
          <div className="eyebrow mb-1.5">Deadlines</div>
          <h1 className="font-display text-[34px] md:text-[40px] leading-[1.05] tracking-[-0.025em] text-brand-950">Every date that matters</h1>
          <p className="text-ink-muted text-[14px] mt-1">Each deal's submission date and the closing date of every tender you saved or that fits you strongly.</p>
        </div>
        <button className="btn-outline" onClick={() => download(`/calendar/deadlines.ics?tenders=${tenders === "saved_strong" ? "saved" : tenders}`, "revenueforge-deadlines.ics").then(() => toast("ok", "Open the file to add the dates to Outlook or Google Calendar. Each has reminders 3 days and 1 day before.")).catch((e) => toast("error", e.message))}
          title="Download every upcoming deal deadline and saved tender as a calendar file, with reminders 3 days and 1 day before">
          <CalendarPlus className="h-4 w-4" /> Add to my calendar
        </button>
      </div>

      {data?.reminders?.length > 0 && (
        <section className="card p-5 border-ember-400/40">
          <div className="flex items-center gap-2 mb-3"><BellRing className="h-[18px] w-[18px] text-ember-600" /><div className="font-bold">Coming up for you</div>
            <span className="chip bg-ember-100 text-ember-600">{data.reminders.length}</span>
            <span className="text-[12.5px] text-ink-muted">Overdue, or due in the next 7 days, that you own or need to approve</span></div>
          <div className="divide-y divide-line-soft">
            {data.reminders.map((e: Ev) => (
              <div key={e.kind + e.id} className="py-2.5 grid md:grid-cols-[150px_1fr] gap-2">
                <div><div className={clsx("text-[13px]", leftTone(e.days_left))}>{left(e.days_left)}</div><div className="text-[12px] text-ink-muted">{longDay(e.date)}</div></div>
                <Row e={e} why={e.why} />
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-ghost p-2" onClick={() => move(-1)} aria-label="Previous month"><ChevronLeft className="h-4 w-4" /></button>
        <button className="btn-ghost p-2" onClick={() => move(1)} aria-label="Next month"><ChevronRight className="h-4 w-4" /></button>
        <div className="font-bold text-[17px] min-w-[180px]">{monthLabel}</div>
        <button className="btn-outline py-1.5 text-[13px]" onClick={() => { const d = new Date(); setCursor(new Date(d.getFullYear(), d.getMonth(), 1)); }}>Today</button>
        {isFetching && <Spinner />}
        <div className="flex-1" />
        <span className="text-[12.5px] text-ink-muted">{counts.deals} deal{counts.deals === 1 ? "" : "s"} · {counts.tenders} tender{counts.tenders === 1 ? "" : "s"}</span>
        <select className="input w-auto py-1.5 text-[13px]" value={tenders} onChange={(e) => setTenders(e.target.value as any)} aria-label="Tenders to show">
          <option value="saved_strong">Tenders: saved + strong fit</option><option value="saved">Tenders: saved only</option><option value="none">Tenders: hide</option>
        </select>
        <label className="text-[13px] inline-flex items-center gap-1.5 text-ink-soft"><input type="checkbox" checked={hideClosed === "1"} onChange={(e) => setHideClosed(e.target.checked ? "1" : "0")} /> Hide submitted and closed deals</label>
        <div className="flex rounded-lg border border-line overflow-hidden">
          <button className={clsx("px-2.5 py-1.5 text-[13px] inline-flex items-center gap-1", view === "month" ? "bg-brand-800 text-white" : "bg-white text-ink-soft")} onClick={() => setView("month")}><CalendarDays className="h-3.5 w-3.5" /> Month</button>
          <button className={clsx("px-2.5 py-1.5 text-[13px] inline-flex items-center gap-1", view === "list" ? "bg-brand-800 text-white" : "bg-white text-ink-soft")} onClick={() => setView("list")}><List className="h-3.5 w-3.5" /> List</button>
        </div>
      </div>

      {isLoading || !data ? <div className="py-16 grid place-items-center"><Spinner /></div> : view === "month" ? <Month cursor={cursor} events={events} today={data.today} /> : <Agenda events={events} />}

      <div className="flex flex-wrap gap-4 text-[12px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-brand-800" /> Deal submission</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-ember-50 border border-ember-400" /> Saved tender closes</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded bg-white border border-dashed border-line" /> Strong-fit tender closes (not saved yet)</span>
      </div>

      {data?.undated?.length > 0 && (
        <section className="card p-5">
          <div className="flex items-center gap-2"><AlertTriangle className="h-[18px] w-[18px] text-ember-600" /><div className="font-bold">Deals without a due date</div></div>
          <p className="text-[13px] text-ink-muted mt-1">These can't go on the calendar until they have a date like 30 Nov 2026. Open the deal and set its due date.</p>
          <ul className="mt-3 space-y-2">
            {data.undated.map((d: Ev) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2 text-[13.5px]"><Link to={d.link} className="font-semibold hover:text-brand-700">{d.title}</Link><OwnerTag owner={d.owner} />
                <span className="text-ink-muted text-[12.5px]">{d.due_text ? `Due date reads "${d.due_text}"` : "No due date"}</span></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
