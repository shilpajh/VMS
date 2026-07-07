import { useState, useEffect } from "react";
import {
  QrCode, ScanFace, CreditCard, UserPlus, ArrowRight, ArrowLeft, CheckCircle2,
  Bell, ShieldAlert, Eye, Camera, LogOut, Siren, FileText, Users, Building2,
  ClipboardList, AlertTriangle, UserCheck, UserX, Clock, Printer, Settings,
  MessageCircle, Send, Sparkles, ScanLine, CalendarPlus, Ticket, X, MapPin,
  Package, Star, Globe, BarChart3, Wifi, Battery, Signal,
} from "lucide-react";

const HOSTS = ["Rahul Mehta — Engineering", "Sara Khan — HR", "David Lee — Security", "Anita Rao — Finance"];
const PURPOSES = ["Business meeting", "Interview", "Contractor work", "Delivery", "Vendor visit"];
const ZONE_OF = { "Business meeting": "floor3", Interview: "hr", "Contractor work": "basement", Delivery: "mailroom", "Vendor visit": "floor2" };
const ZONE_LABEL = { lobby: "Lobby", floor2: "Floor 2", floor3: "Floor 3", hr: "HR suite", basement: "Basement", mailroom: "Mailroom" };

const mins = (n) => Date.now() - n * 60000;
const fmt = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const initials = (n) => n.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();
const font = { fontFamily: "'Space Grotesk','Segoe UI',system-ui,sans-serif" };
const mono = { fontFamily: "'IBM Plex Mono',ui-monospace,monospace" };

const seedVisitors = [
  { id: 1, name: "Anita Kapoor", company: "Kapoor Ventures", host: HOSTS[3], purpose: "Business meeting", method: "QR invite", status: "checked-in", badge: "V-20455", zoneKey: "floor3", checkinAt: mins(64), windowMins: 240, vip: true, hostResponse: "On my way" },
  { id: 2, name: "Joseph D'Souza", company: "FixIt Services", host: HOSTS[2], purpose: "Contractor work", method: "ID scan", status: "checked-in", badge: "V-20388", zoneKey: "basement", checkinAt: mins(165), windowMins: 120, hostResponse: "Approved" },
  { id: 3, name: "Meera Thomas", company: "—", host: HOSTS[1], purpose: "Interview", method: "QR invite", status: "checked-in", badge: "V-20458", zoneKey: "hr", checkinAt: mins(22), windowMins: 240, hostResponse: null },
];

const seedInvites = [
  { id: 1, name: "Arjun Patel", company: "Zenith Consulting", host: HOSTS[3], purpose: "Vendor visit", ref: "QR-88214", used: false },
  { id: 2, name: "Lena Fischer", company: "Nordwind GmbH", host: HOSTS[0], purpose: "Business meeting", ref: "QR-88215", used: false },
];

const seedAlerts = [
  { id: 1, sev: "danger", title: "Tailgating detected — turnstile B2", detail: "Two people passed on one credential. Video clip attached.", at: mins(19), reviewed: false },
];

export default function App() {
  const [view, setView] = useState("kiosk");
  const [visitors, setVisitors] = useState(seedVisitors);
  const [invites, setInvites] = useState(seedInvites);
  const [deliveries, setDeliveries] = useState([{ id: 1, courier: "BlueDart", pkg: "Document envelope", host: HOSTS[1], at: mins(40), collected: true }]);
  const [alerts, setAlerts] = useState(seedAlerts);
  const [watchlist, setWatchlist] = useState(["Victor Crane"]);
  const [evac, setEvac] = useState(false);
  const [badgeSeq, setBadgeSeq] = useState(20461);
  const [toast, setToast] = useState(null);
  const [, setTick] = useState(0);

  useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 15000); return () => clearInterval(t); }, []);

  const ping = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3400); };
  const addAlert = (a) => setAlerts((s) => [{ id: Date.now(), at: Date.now(), reviewed: false, ...a }, ...s]);
  const update = (id, patch) => setVisitors((s) => s.map((v) => (v.id === id ? { ...v, ...patch } : v)));

  const checkIn = ({ name, company, host, purpose, method, inviteId, requireApproval }) => {
    const flagged = watchlist.some((w) => w.toLowerCase() === name.toLowerCase());
    const needsOk = requireApproval && !flagged;
    const badge = needsOk ? "—" : `V-${badgeSeq}`;
    if (!needsOk) setBadgeSeq((n) => n + 1);
    const v = { id: Date.now(), name, company: company || "—", host, purpose, method, badge, zoneKey: ZONE_OF[purpose], checkinAt: Date.now(), windowMins: 240, status: flagged ? "held" : needsOk ? "awaiting-approval" : "checked-in", flagged, hostResponse: null };
    setVisitors((s) => [v, ...s]);
    if (inviteId) setInvites((s) => s.map((i) => (i.id === inviteId ? { ...i, used: true } : i)));
    if (flagged) addAlert({ sev: "danger", title: `Watchlist match — ${name}`, detail: "Check-in held at kiosk. Security review required before entry." });
    else if (needsOk) ping(`Approval request sent to ${host.split(" —")[0]} — walk-in visitor ${name}`);
    else ping(`${host.split(" —")[0]} notified: ${name} has arrived`);
    return v;
  };

  const slipEntry = ({ name, company, host, purpose, slipRef }) => {
    const v = { id: Date.now(), name, company: company || "—", host, purpose, method: `Paper slip ${slipRef}`, badge: "—", zoneKey: ZONE_OF[purpose], checkinAt: Date.now(), windowMins: 240, status: "awaiting-approval", hostResponse: null };
    setVisitors((s) => [v, ...s]);
    ping(`Confirmation request sent to ${host.split(" —")[0]}`);
  };

  const createInvite = (inv) => {
    const ref = `QR-${88216 + invites.length}`;
    setInvites((s) => [...s, { id: Date.now(), ...inv, ref, used: false }]);
    ping(`Invite ${ref} sent to ${inv.name} by email and SMS`);
  };

  const hostAct = (v, action) => {
    if (action === "Approve slip") {
      const badge = `V-${badgeSeq}`; setBadgeSeq((n) => n + 1);
      update(v.id, { status: "checked-in", badge, checkinAt: Date.now(), hostResponse: "Approved" });
      ping(`${v.name} approved — badge ${badge} issued at reception`);
    } else if (action === "Deny") {
      update(v.id, { status: "denied", hostResponse: "Denied" });
      addAlert({ sev: "warning", title: `Entry denied — ${v.name}`, detail: "Host denied the visit. Badge deactivated, reception informed." });
    } else {
      update(v.id, { hostResponse: action });
      ping(`Reception told: ${action.toLowerCase()}`);
    }
  };

  const addDelivery = (d) => {
    setDeliveries((s) => [{ id: Date.now(), at: Date.now(), collected: false, ...d }, ...s]);
    ping(`${d.host.split(" —")[0]} notified: package from ${d.courier} at reception`);
  };
  const markCollected = (id) => setDeliveries((s) => s.map((d) => (d.id === id ? { ...d, collected: true } : d)));
  const kioskCheckout = (v) => { update(v.id, { status: "checked-out" }); ping(`${v.name} checked out — badge ${v.badge} deactivated`); };

  const onSite = visitors.filter((v) => v.status === "checked-in" || v.status === "safe");
  const isOver = (v) => v.status === "checked-in" && (Date.now() - v.checkinAt) / 60000 > v.windowMins;
  const activeAlerts = alerts.filter((a) => !a.reviewed).length + onSite.filter(isOver).length;
  const pendingHost = visitors.filter((v) => (v.status === "checked-in" && !v.hostResponse) || v.status === "awaiting-approval" || v.status === "held");

  const tabs = [
    ["kiosk", "Kiosk", QrCode],
    ["reception", "Reception", ClipboardList],
    ["security", "Security", ShieldAlert, activeAlerts],
    ["host", "Host app", Bell, pendingHost.length + deliveries.filter((d) => !d.collected).length],
    ["admin", "Admin", Settings],
  ];

  const activeTab = tabs.find((t) => t[0] === view);

  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 flex" style={font}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');
        @keyframes scanpulse { 0%,100%{opacity:1} 50%{opacity:.35} }
        @keyframes scanline { 0%{top:8%} 50%{top:88%} 100%{top:8%} }
        @keyframes dotblink { 0%,100%{opacity:1} 50%{opacity:.5} }
        .scanframe { animation: scanpulse 1.6s ease-in-out infinite; }
        .scanline { animation: scanline 2.2s ease-in-out infinite; }
        .livedot { animation: dotblink 1.4s ease-in-out infinite; }
        * { font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }
      `}</style>

      <aside className="hidden md:flex md:flex-col w-64 shrink-0 bg-slate-900 text-slate-300 min-h-screen sticky top-0">
        <div className="flex items-center gap-2 px-5 h-16 border-b border-slate-800/60">
          <div className="bg-violet-500 rounded-lg p-1.5"><ShieldAlert size={18} className="text-white" /></div>
          <span className="text-white font-semibold tracking-tight text-[15px]">Onsite VMS</span>
        </div>
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Modules</p>
          {tabs.map(([id, label, Icon, count]) => (
            <button key={id} onClick={() => setView(id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${view === id ? "bg-slate-800 text-white" : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"}`}>
              <Icon size={17} className={view === id ? "text-violet-400" : ""} />
              <span className="flex-1 text-left">{label}</span>
              {count > 0 && <span className="text-xs bg-rose-500 text-white rounded-full px-1.5 py-0.5 leading-none">{count}</span>}
            </button>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-slate-800/60">
          <div className="flex items-center gap-2 text-xs text-slate-400" style={mono}>
            <span className="w-2 h-2 rounded-full bg-emerald-400 livedot inline-block" /> live · {onSite.length} on site
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0">
        <header className="h-16 bg-white border-b border-slate-200 px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30">
          <div className="flex items-center gap-3">
            <div className="md:hidden bg-violet-500 rounded-lg p-1.5"><ShieldAlert size={16} className="text-white" /></div>
            <div>
              <h1 className="text-base font-semibold text-slate-800">{activeTab ? activeTab[1] : ""}</h1>
              <p className="text-xs text-slate-400 hidden sm:block">Onsite — visitor management prototype</p>
            </div>
          </div>
          <nav className="md:hidden flex gap-1 overflow-x-auto">
            {tabs.map(([id, label, Icon, count]) => (
              <button key={id} onClick={() => setView(id)}
                className={`relative flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs whitespace-nowrap ${view === id ? "bg-violet-50 text-violet-700 font-medium" : "text-slate-500"}`}>
                <Icon size={13} /> {label}
                {count > 0 && <span className="ml-0.5 text-[10px] bg-rose-500 text-white rounded-full px-1">{count}</span>}
              </button>
            ))}
          </nav>
        </header>

        {evac && (
          <div className="bg-rose-600 text-white px-6 py-2 text-sm flex items-center gap-2">
            <Siren size={16} /> Evacuation in progress — all badges frozen. Muster list live in the Security view.
          </div>
        )}

        <main className="max-w-4xl mx-auto p-4 sm:p-6">
          {view === "kiosk" && <Kiosk checkIn={checkIn} invites={invites} visitors={visitors} kioskCheckout={kioskCheckout} />}
          {view === "reception" && <Reception slipEntry={slipEntry} visitors={visitors} isOver={isOver} addDelivery={addDelivery} deliveries={deliveries} />}
          {view === "security" && (
            <PhoneFrame appName="Onsite Security" AppIcon={ShieldAlert}>
              <Security visitors={visitors} onSite={onSite} isOver={isOver} alerts={alerts} setAlerts={setAlerts} update={update} evac={evac} setEvac={setEvac} addAlert={addAlert} ping={ping} />
            </PhoneFrame>
          )}
          {view === "host" && (
            <PhoneFrame appName="Onsite Host" AppIcon={Bell}>
              <HostApp pending={pendingHost} recent={visitors} hostAct={hostAct} createInvite={createInvite} invites={invites} deliveries={deliveries} markCollected={markCollected} />
            </PhoneFrame>
          )}
          {view === "admin" && <Admin watchlist={watchlist} setWatchlist={setWatchlist} />}
        </main>
      </div>

      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-slate-900 text-slate-100 text-sm px-4 py-2 rounded-lg flex items-center gap-2 shadow-lg z-50">
          <Bell size={14} className="text-violet-400" /> {toast}
        </div>
      )}
    </div>
  );
}

const Card = ({ children, className = "" }) => <div className={`bg-white border border-slate-200/70 shadow-sm rounded-xl p-5 ${className}`}>{children}</div>;

function Pill({ tone, children }) {
  const map = { green: "bg-emerald-100 text-emerald-800", amber: "bg-amber-100 text-amber-800", red: "bg-rose-100 text-rose-800", gray: "bg-slate-200 text-slate-700", purple: "bg-violet-100 text-violet-800" };
  return <span className={`text-xs px-2.5 py-0.5 rounded-full whitespace-nowrap ${map[tone]}`}>{children}</span>;
}

const Avatar = ({ name, tone = "bg-emerald-100 text-emerald-800", size = "w-9 h-9" }) => (
  <div className={`${size} rounded-full flex items-center justify-center text-xs font-medium shrink-0 ${tone}`}>{initials(name)}</div>
);

function PhoneFrame({ appName, AppIcon, accent = "bg-slate-900", children }) {
  return (
    <div className="flex justify-center">
      <div className="w-full max-w-sm bg-slate-900 rounded-3xl p-2 shadow-xl">
        <div className="bg-slate-100 rounded-2xl overflow-hidden">
          <div className={`${accent} text-slate-100`}>
            <div className="flex items-center justify-between px-4 pt-2 text-xs">
              <span style={mono}>{new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
              <span className="flex items-center gap-1.5"><Signal size={12} /><Wifi size={12} /><Battery size={14} /></span>
            </div>
            <div className="flex items-center gap-2 px-4 py-2.5">
              <AppIcon size={16} className="text-violet-400" />
              <span className="text-sm font-medium">{appName}</span>
            </div>
          </div>
          <div className="p-3 h-[560px] overflow-y-auto">{children}</div>
          <div className="flex justify-center py-2 bg-slate-100"><span className="w-24 h-1 rounded-full bg-slate-300" /></div>
        </div>
      </div>
    </div>
  );
}

function StatusPill({ v, isOver }) {
  if (v.status === "checked-in" && isOver && isOver(v)) return <Pill tone="amber">Overstay</Pill>;
  if (v.status === "checked-in" && v.vip) return <Pill tone="purple">VIP</Pill>;
  if (v.status === "checked-in") return <Pill tone="green">Checked in</Pill>;
  if (v.status === "awaiting-approval") return <Pill tone="gray">Pending host</Pill>;
  if (v.status === "held") return <Pill tone="red">Held</Pill>;
  if (v.status === "denied") return <Pill tone="red">Denied</Pill>;
  if (v.status === "safe") return <Pill tone="green">Safe</Pill>;
  return <Pill tone="gray">Checked out</Pill>;
}

/* ================= Kiosk ================= */
function Kiosk({ checkIn, invites, visitors, kioskCheckout }) {
  const [step, setStep] = useState("home");
  const [method, setMethod] = useState("");
  const [f, setF] = useState({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0], inviteId: null });
  const [agree, setAgree] = useState(false);
  const [dpdp, setDpdp] = useState(false);
  const [err, setErr] = useState("");
  const [issued, setIssued] = useState(null);
  const [scanMsg, setScanMsg] = useState("");
  const [facePhase, setFacePhase] = useState(0);
  const [chatOpen, setChatOpen] = useState(false);
  const [count, setCount] = useState(null);
  const [photoDone, setPhotoDone] = useState(false);
  const [pendingId, setPendingId] = useState(null);
  const [lang, setLang] = useState("en");
  const [rating, setRating] = useState(0);

  const T = {
    en: { welcome: "Welcome to Acme Corp", how: "How would you like to check in?", qr: "Scan QR invite", face: "Face check-in", idd: "Scan ID document", walk: "Walk-in visitor", out: "Leaving? Tap here to check out", hint: "Paper gate pass? A receptionist will scan and verify it — see the Reception tab. Questions? Tap the assistant at the bottom right." },
    hi: { welcome: "एक्मे कॉर्प में आपका स्वागत है", how: "आप कैसे चेक-इन करना चाहेंगे?", qr: "QR निमंत्रण स्कैन करें", face: "फेस चेक-इन", idd: "पहचान पत्र स्कैन करें", walk: "वॉक-इन आगंतुक", out: "जा रहे हैं? चेक-आउट के लिए यहाँ टैप करें", hint: "कागज़ का गेट पास है? रिसेप्शन डेस्क पर जाएँ — वे स्कैन करके सत्यापित करेंगे।" },
  };
  const t = T[lang];

  const isWalkIn = method === "Walk-in visitor";
  const pending = visitors.find((v) => v.id === pendingId);

  useEffect(() => {
    if (step !== "waiting" || !pending) return;
    if (pending.status === "checked-in") {
      setIssued(pending); setStep("printing");
      setTimeout(() => setStep("badge"), 1700);
    } else if (pending.status === "denied") {
      setStep("deniedscreen");
    }
  }, [step, pending && pending.status]);

  const reset = () => { setStep("home"); setMethod(""); setF({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0], inviteId: null }); setAgree(false); setDpdp(false); setErr(""); setIssued(null); setScanMsg(""); setFacePhase(0); setCount(null); setPhotoDone(false); setPendingId(null); setRating(0); };

  const takePhoto = () => {
    setCount(3);
    [2, 1, 0].forEach((n, i) => setTimeout(() => {
      setCount(n);
      if (n === 0) setTimeout(() => { setCount(null); setPhotoDone(true); }, 300);
    }, 800 * (i + 1)));
  };

  const finishWalkIn = () => {
    const v = checkIn({ ...f, method, requireApproval: true });
    if (v.status === "held") { setIssued(v); setStep("badge"); }
    else { setPendingId(v.id); setStep("waiting"); }
  };

  const pick = (m) => {
    setMethod(m); setErr("");
    if (m === "Scan QR invite") setStep("qr");
    else if (m === "Face check-in") { setStep("face"); runFace(); }
    else if (m === "Scan ID document") { setStep("idscan"); setIdPhase(0); }
    else { setF({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0], inviteId: null }); setStep("details"); }
  };

  const [idPhase, setIdPhase] = useState(0);
  const [idDoc, setIdDoc] = useState(null);
  const ID_STEPS = ["Scanning document…", "Reading text from the document (OCR)…", "Checking security features — hologram, fonts, MRZ…", "Document genuine — details extracted"];
  const SAMPLE_IDS = [
    { label: "Driver's license", name: "Meena Iyer", num: "DL-4821 9930", doc: "Driving licence · India" },
    { label: "Passport", name: "Tom Becker", num: "P 8842137", doc: "Passport · Germany" },
  ];
  const scanId = (d) => {
    setIdDoc(d); setIdPhase(1);
    [2, 3, 4].forEach((n, i) => setTimeout(() => {
      setIdPhase(n);
      if (n === 4) setTimeout(() => { setF({ name: d.name, company: "", host: HOSTS[0], purpose: PURPOSES[0], inviteId: null }); setStep("details"); }, 700);
    }, 900 * (i + 1)));
  };

  const FACE_STEPS = ["Detecting face…", "Liveness check — real person confirmed", "Matching against enrolled visitors…", "Match found: Priya Sharma · 98.7% confidence"];
  const runFace = () => {
    setFacePhase(0);
    [1, 2, 3, 4].forEach((n, i) => setTimeout(() => {
      setFacePhase(n);
      if (n === 4) setTimeout(() => { setF({ name: "Priya Sharma", company: "Northwind Ltd", host: HOSTS[0], purpose: PURPOSES[0], inviteId: null }); setStep("details"); }, 700);
    }, 900 * (i + 1)));
  };

  const scanInvite = (inv) => {
    setScanMsg(`Reading pass ${inv.ref}…`);
    setTimeout(() => {
      setScanMsg("");
      setF({ name: inv.name, company: inv.company, host: inv.host, purpose: inv.purpose, inviteId: inv.id });
      setStep("details");
    }, 900);
  };

  const toNda = () => { if (!f.name.trim()) { setErr("Enter the visitor's full name"); return; } setErr(""); setStep("nda"); };
  const sign = () => {
    if (!agree || !dpdp) { setErr("Tick both the agreement and data-consent boxes to continue"); return; }
    setErr("");
    if (isWalkIn) { setStep("photo"); return; }
    setStep("printing");
    setTimeout(() => { const v = checkIn({ ...f, method }); setIssued(v); setStep("badge"); }, 1700);
  };

  const open = invites.filter((i) => !i.used);
  const dots = ["home", "details", "nda", "badge"];
  const dotIdx = step === "qr" || step === "face" ? 0 : Math.max(0, dots.indexOf(step === "printing" ? "badge" : step));

  return (
    <div className="bg-slate-200 rounded-2xl p-4 sm:p-6 relative">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 text-sm text-slate-600"><Building2 size={16} /> Main lobby kiosk</div>
        <div className="flex gap-1.5">{dots.map((d, i) => <span key={d} className={`w-2 h-2 rounded-full ${i === dotIdx ? "bg-emerald-600" : "bg-slate-400"}`} />)}</div>
      </div>

      <Card className="min-h-96">
        {step === "home" && (
          <>
            <div className="flex items-start justify-between mb-1">
              <h2 className="text-xl font-semibold text-slate-800">{t.welcome}</h2>
              <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="flex items-center gap-1 text-xs border border-slate-300 rounded-lg px-2.5 py-1.5 hover:bg-slate-100">
                <Globe size={13} /> {lang === "en" ? "हिन्दी" : "English"}
              </button>
            </div>
            <p className="text-sm text-slate-500 mb-5">{t.how}</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[[t.qr, "Scan QR invite", QrCode], [t.face, "Face check-in", ScanFace], [t.idd, "Scan ID document", CreditCard], [t.walk, "Walk-in visitor", UserPlus]].map(([label, key, Icon]) => (
                <button key={key} onClick={() => pick(key)} className="flex flex-col items-center gap-2 border border-slate-300 rounded-xl py-5 px-2 hover:border-violet-500 hover:bg-violet-50">
                  <Icon size={26} className="text-slate-700" /><span className="text-xs text-center">{label}</span>
                </button>
              ))}
            </div>
            <button onClick={() => setStep("checkout")} className="mt-4 w-full flex items-center justify-center gap-2 text-sm border border-slate-300 rounded-xl py-3 hover:border-violet-500 hover:bg-violet-50 text-slate-600">
              <LogOut size={15} /> {t.out}
            </button>
            <p className="text-xs text-slate-400 mt-4">{t.hint}</p>
          </>
        )}

        {step === "checkout" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Check out</h2>
            <p className="text-sm text-slate-500 mb-4">Tap your name — your badge will be deactivated immediately.</p>
            <div className="space-y-2 max-w-sm">
              {visitors.filter((v) => v.status === "checked-in").map((v) => (
                <button key={v.id} onClick={() => { kioskCheckout(v); setStep("feedback"); }} className="w-full flex items-center gap-3 border border-slate-300 rounded-lg px-3 py-2.5 hover:border-violet-500 hover:bg-violet-50 text-left">
                  <Avatar name={v.name} />
                  <span className="text-sm">{v.name}<span className="block text-xs text-slate-500">badge <span style={mono}>{v.badge}</span> · {ZONE_LABEL[v.zoneKey]}</span></span>
                </button>
              ))}
              {visitors.filter((v) => v.status === "checked-in").length === 0 && <p className="text-sm text-slate-400">Nobody is currently checked in.</p>}
            </div>
            <button onClick={reset} className="mt-4 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100 flex items-center gap-1"><ArrowLeft size={14} /> Back</button>
          </>
        )}

        {step === "feedback" && (
          <div className="text-center py-8">
            <CheckCircle2 size={40} className="mx-auto text-emerald-600 mb-3" />
            <h2 className="text-xl font-semibold text-slate-800 mb-1">You're checked out</h2>
            <p className="text-sm text-slate-500 mb-5">Badge deactivated. How was your visit today?</p>
            <div className="flex justify-center gap-2 mb-4">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} onClick={() => setRating(n)}>
                  <Star size={30} className={n <= rating ? "text-amber-500" : "text-slate-300"} fill={n <= rating ? "currentColor" : "none"} />
                </button>
              ))}
            </div>
            {rating > 0 && <p className="text-sm text-emerald-700 mb-4">Thank you for your feedback!</p>}
            <button onClick={reset} className="text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">Done</button>
          </div>
        )}

        {step === "qr" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Hold your QR pass to the camera</h2>
            <p className="text-sm text-slate-500 mb-4">The pass from your invite email or SMS.</p>
            <div className="relative mx-auto w-48 h-48 border-2 border-violet-500 rounded-xl scanframe mb-2 overflow-hidden bg-slate-50">
              <QrCode size={90} className="absolute inset-0 m-auto text-slate-300" />
              <div className="scanline absolute left-2 right-2 h-0.5 bg-violet-500" />
            </div>
            {scanMsg ? (
              <p className="text-sm text-emerald-700 text-center flex items-center justify-center gap-2"><ScanLine size={15} /> {scanMsg}</p>
            ) : (
              <>
                <p className="text-xs text-slate-400 text-center mb-3">Demo: no real camera here — tap an expected visitor pass below to simulate the scan.</p>
                <div className="grid sm:grid-cols-2 gap-2">
                  {open.map((inv) => (
                    <button key={inv.id} onClick={() => scanInvite(inv)} className="flex items-center gap-3 border border-slate-300 rounded-lg px-3 py-2 hover:border-violet-500 hover:bg-violet-50 text-left">
                      <Ticket size={18} className="text-emerald-700 shrink-0" />
                      <span className="text-sm">{inv.name}<span className="block text-xs text-slate-500" style={mono}>{inv.ref}</span></span>
                    </button>
                  ))}
                  {open.length === 0 && <p className="text-sm text-slate-400 col-span-2">No unused invites — create one in the Host app tab.</p>}
                </div>
              </>
            )}
            <button onClick={reset} className="mt-4 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100 flex items-center gap-1"><ArrowLeft size={14} /> Back</button>
          </>
        )}

        {step === "face" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Look at the camera</h2>
            <p className="text-sm text-slate-500 mb-4">Touchless check-in for enrolled visitors.</p>
            <div className="relative mx-auto w-48 h-48 border-2 border-violet-500 rounded-full scanframe mb-4 flex items-center justify-center bg-slate-50">
              <ScanFace size={80} className="text-slate-300" />
            </div>
            <div className="max-w-xs mx-auto space-y-2">
              {FACE_STEPS.map((s, i) => (
                <div key={s} className={`flex items-center gap-2 text-sm ${facePhase > i ? "text-emerald-700" : facePhase === i ? "text-slate-600" : "text-slate-300"}`}>
                  {facePhase > i ? <CheckCircle2 size={15} /> : <span className={`w-3.5 h-3.5 rounded-full border ${facePhase === i ? "border-violet-500 livedot" : "border-slate-300"}`} />}
                  {s}
                </div>
              ))}
            </div>
            <button onClick={reset} className="mt-5 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100 flex items-center gap-1"><ArrowLeft size={14} /> Cancel</button>
          </>
        )}

        {step === "idscan" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Place your ID on the scanner</h2>
            <p className="text-sm text-slate-500 mb-4">Passport, driver's license, or national ID — face up.</p>
            <div className="relative mx-auto w-64 h-40 border-2 border-violet-500 rounded-xl scanframe mb-3 overflow-hidden bg-slate-50 flex items-center justify-center">
              {idDoc ? (
                <div className="text-center px-3">
                  <CreditCard size={34} className="mx-auto text-slate-400 mb-1" />
                  <p className="text-sm font-medium">{idDoc.name}</p>
                  <p className="text-xs text-slate-500" style={mono}>{idDoc.num}</p>
                  <p className="text-xs text-slate-400">{idDoc.doc}</p>
                </div>
              ) : (
                <CreditCard size={54} className="text-slate-300" />
              )}
              {idPhase > 0 && idPhase < 4 && <div className="scanline absolute left-2 right-2 h-0.5 bg-violet-500" />}
            </div>
            {idPhase === 0 ? (
              <>
                <p className="text-xs text-slate-400 text-center mb-3">Demo: no real scanner here — tap a sample document to simulate placing it.</p>
                <div className="grid grid-cols-2 gap-2 max-w-sm mx-auto">
                  {SAMPLE_IDS.map((d) => (
                    <button key={d.label} onClick={() => scanId(d)} className="flex flex-col items-center gap-1 border border-slate-300 rounded-lg py-3 px-2 hover:border-violet-500 hover:bg-violet-50">
                      <CreditCard size={20} className="text-emerald-700" />
                      <span className="text-xs">{d.label}</span>
                      <span className="text-xs text-slate-400">{d.name}</span>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className="max-w-xs mx-auto space-y-2">
                {ID_STEPS.map((s, i) => (
                  <div key={s} className={`flex items-center gap-2 text-sm ${idPhase > i + 1 ? "text-emerald-700" : idPhase === i + 1 ? "text-slate-600" : "text-slate-300"}`}>
                    {idPhase > i + 1 ? <CheckCircle2 size={15} /> : <span className={`w-3.5 h-3.5 rounded-full border shrink-0 ${idPhase === i + 1 ? "border-violet-500 livedot" : "border-slate-300"}`} />}
                    {s}
                  </div>
                ))}
              </div>
            )}
            <button onClick={reset} className="mt-5 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100 flex items-center gap-1"><ArrowLeft size={14} /> Cancel</button>
          </>
        )}

        {step === "details" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">{f.inviteId ? "Confirm your details" : "Your details"}</h2>
            <p className="text-sm text-slate-500 mb-4">
              Method: {method}
              {f.inviteId && " — invite found, details pulled from your pre-registration"}
              {method === "Face check-in" && " — returning visitor recognized, details pre-filled"}
              {method === "Scan ID document" && " — name read from your document, add the rest"}
            </p>
            <div className="grid sm:grid-cols-2 gap-3 mb-3">
              <label className="text-xs text-slate-500">Full name
                <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Priya Sharma" className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
              </label>
              <label className="text-xs text-slate-500">Company
                <input value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} placeholder="Northwind Ltd" className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
              </label>
              <label className="text-xs text-slate-500">Who are you visiting?
                <select value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">
                  {HOSTS.map((h) => <option key={h}>{h}</option>)}
                </select>
              </label>
              <label className="text-xs text-slate-500">Purpose of visit
                <select value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">
                  {PURPOSES.map((p) => <option key={p}>{p}</option>)}
                </select>
              </label>
            </div>
            {err && <p className="text-xs text-rose-600 mb-2">{err}</p>}
            <div className="flex justify-between">
              <button onClick={reset} className="flex items-center gap-1 text-sm border border-slate-300 rounded-lg px-3 py-2 hover:bg-slate-100"><ArrowLeft size={14} /> Back</button>
              <button onClick={toNda} className="flex items-center gap-1 text-sm bg-violet-500 text-white rounded-lg px-4 py-2 hover:bg-violet-600">Continue <ArrowRight size={14} /></button>
            </div>
          </>
        )}

        {step === "nda" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Sign the visitor agreement</h2>
            <p className="text-sm text-slate-500 mb-3">Non-disclosure and site safety agreement, v2.3</p>
            <div className="border border-slate-200 bg-slate-50 rounded-lg p-3 text-xs text-slate-600 leading-relaxed mb-3">
              By signing, you agree to keep confidential any information observed during your visit, remain within authorized zones, wear your badge visibly at all times, and follow escort and safety instructions from your host or security staff.
            </div>
            <label className="flex items-center gap-2 text-sm mb-2">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> I have read and agree to the terms
            </label>
            <label className="flex items-start gap-2 text-sm mb-4">
              <input type="checkbox" checked={dpdp} onChange={(e) => setDpdp(e.target.checked)} className="mt-0.5" /> <span>I consent to my personal data being processed for this visit and deleted after the retention period <span className="text-xs text-slate-400">(DPDP Act 2023)</span></span>
            </label>
            {err && <p className="text-xs text-rose-600 mb-2">{err}</p>}
            <div className="flex justify-between">
              <button onClick={() => setStep("details")} className="flex items-center gap-1 text-sm border border-slate-300 rounded-lg px-3 py-2 hover:bg-slate-100"><ArrowLeft size={14} /> Back</button>
              <button onClick={sign} className="flex items-center gap-1 text-sm bg-violet-500 text-white rounded-lg px-4 py-2 hover:bg-violet-600"><FileText size={14} /> Sign and continue</button>
            </div>
          </>
        )}

        {step === "photo" && (
          <>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Photo for your badge</h2>
            <p className="text-sm text-slate-500 mb-4">Walk-in visitors need a photo and host approval before a badge is issued.</p>
            <div className="relative mx-auto w-44 h-44 rounded-full border-2 border-violet-500 scanframe mb-4 flex items-center justify-center bg-slate-50 overflow-hidden">
              {photoDone ? (
                <div className="w-full h-full bg-emerald-100 flex items-center justify-center text-3xl font-medium text-emerald-800">{initials(f.name || "V ?")}</div>
              ) : count !== null && count > 0 ? (
                <span className="text-5xl font-medium text-emerald-700">{count}</span>
              ) : count === 0 ? (
                <span className="text-xl text-emerald-700 flex items-center gap-2"><Camera size={22} /> Captured</span>
              ) : (
                <Camera size={54} className="text-slate-300" />
              )}
            </div>
            {photoDone ? (
              <div className="text-center">
                <p className="text-sm text-emerald-700 mb-4 flex items-center justify-center gap-1"><CheckCircle2 size={15} /> Photo captured and attached to your visit</p>
                <button onClick={finishWalkIn} className="text-sm bg-violet-500 text-white rounded-lg px-5 py-2.5 hover:bg-violet-600 flex items-center gap-1 mx-auto">Request host approval <ArrowRight size={14} /></button>
                <button onClick={() => { setPhotoDone(false); setCount(null); }} className="block mx-auto mt-2 text-xs text-slate-500 hover:underline">Retake photo</button>
              </div>
            ) : (
              <div className="text-center">
                <button onClick={takePhoto} disabled={count !== null} className="text-sm bg-violet-500 text-white rounded-lg px-5 py-2.5 hover:bg-violet-600 disabled:opacity-50 flex items-center gap-2 mx-auto"><Camera size={15} /> {count !== null ? "Hold still…" : "Take photo"}</button>
                <button onClick={() => setStep("nda")} className="block mx-auto mt-3 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">Back</button>
              </div>
            )}
          </>
        )}

        {step === "waiting" && pending && (
          <div className="text-center py-8">
            <div className="mx-auto w-14 h-14 rounded-full border-2 border-violet-500 scanframe flex items-center justify-center mb-4"><Bell size={24} className="text-emerald-700" /></div>
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Waiting for {pending.host.split(" —")[0]} to approve</h2>
            <p className="text-sm text-slate-500 mb-1">Your host has been notified on their phone.</p>
            <p className="text-xs text-slate-400 mb-5">Demo: switch to the Host app tab, tap Confirm (or Deny), then come back here — this screen updates live.</p>
            <div className="inline-flex items-center gap-2 text-xs bg-slate-100 rounded-full px-3 py-1.5 text-slate-600">
              <span className="w-2 h-2 rounded-full bg-amber-500 livedot" /> Status: awaiting approval
            </div>
            <button onClick={reset} className="block mx-auto mt-6 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">Cancel check-in</button>
          </div>
        )}

        {step === "deniedscreen" && (
          <div className="text-center py-8">
            <UserX size={40} className="mx-auto text-rose-600 mb-3" />
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Entry not approved</h2>
            <p className="text-sm text-slate-500 mb-5">Your host declined this visit. Please contact them directly or ask at the reception desk.</p>
            <button onClick={reset} className="text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">Back to start</button>
          </div>
        )}

        {step === "printing" && (
          <div className="text-center py-12">
            <Printer size={40} className="mx-auto text-slate-500 mb-4" />
            <p className="text-lg font-semibold text-slate-800 mb-1">Printing your badge…</p>
            <p className="text-sm text-slate-500 mb-5">Screening against watchlist · activating access credential</p>
            <div className="w-56 h-2 bg-slate-200 rounded-full mx-auto overflow-hidden">
              <div className="h-full bg-emerald-600 rounded-full" style={{ width: "100%", transition: "width 1.6s linear", animation: "none" }} ref={(el) => { if (el) { el.style.width = "0%"; requestAnimationFrame(() => (el.style.width = "100%")); } }} />
            </div>
          </div>
        )}

        {step === "badge" && issued && (issued.status === "held" ? (
          <div className="text-center py-8">
            <ShieldAlert size={40} className="mx-auto text-rose-600 mb-3" />
            <h2 className="text-xl font-semibold text-slate-800 mb-1">Please see the reception desk</h2>
            <p className="text-sm text-slate-500 mb-5">Your check-in needs a quick manual review before a badge can be issued.</p>
            <button onClick={reset} className="text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">Back to start</button>
            <p className="text-xs text-slate-400 mt-4">(Demo: this name is on the watchlist — see the Security and Admin tabs.)</p>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-4"><CheckCircle2 size={22} className="text-emerald-600" /><h2 className="text-xl font-semibold text-slate-800">You're checked in</h2></div>
            <div className="flex flex-wrap gap-4">
              <div className="flex-1 min-w-56 bg-slate-50 border border-slate-200 rounded-xl p-4">
                <div className="flex items-center gap-3 mb-3">
                  <Avatar name={issued.name} size="w-11 h-11" />
                  <div><p className="text-sm font-medium">{issued.name}</p><p className="text-xs text-slate-500">Visitor — {issued.purpose.toLowerCase()}</p></div>
                </div>
                <div className="text-xs space-y-1.5">
                  <div className="flex justify-between"><span className="text-slate-500">Host</span><span>{issued.host.split(" —")[0]}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Zone</span><span>{ZONE_LABEL[issued.zoneKey]}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Valid</span><span>{issued.windowMins / 60} hours</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">Badge</span><span style={mono}>{issued.badge}</span></div>
                </div>
              </div>
              <div className="min-w-36 bg-slate-50 border border-slate-200 rounded-xl p-4 flex flex-col items-center justify-center gap-2">
                <QrCode size={64} /><span className="text-xs text-slate-400">Tap at turnstile</span>
              </div>
            </div>
            <p className="text-sm text-slate-500 mt-4 flex items-center gap-2"><Bell size={15} /> {issued.host.split(" —")[0]} has been notified — check the Host app tab.</p>
            <button onClick={reset} className="mt-4 text-sm border border-slate-300 rounded-lg px-4 py-2 hover:bg-slate-100">New check-in</button>
          </>
        ))}
      </Card>

      <button onClick={() => setChatOpen(true)} className="absolute bottom-6 right-6 bg-violet-500 text-white rounded-full p-3 hover:bg-violet-600 shadow" title="AI assistant">
        <Sparkles size={20} />
      </button>
      {chatOpen && <KioskAssistant onClose={() => setChatOpen(false)} />}
    </div>
  );
}

/* ================= AI kiosk assistant (scripted demo) ================= */
function KioskAssistant({ onClose }) {
  const [msgs, setMsgs] = useState([{ who: "bot", text: "Hi, I'm the lobby assistant. Ask me about wifi, parking, restrooms, coffee, or what to do if your host is late." }]);
  const [input, setInput] = useState("");
  const reply = (q) => {
    const s = q.toLowerCase();
    if (s.includes("wifi") || s.includes("wi-fi")) return "Guest wifi: network 'Acme-Guest', password shown on your badge receipt. It activates once you're checked in.";
    if (s.includes("park")) return "Visitor parking is in Basement 1 — take a ticket at the barrier and reception will validate it when you check out.";
    if (s.includes("rest") || s.includes("toilet") || s.includes("bath") || s.includes("washroom")) return "Restrooms are behind the elevators to your left, next to the water station.";
    if (s.includes("coffee") || s.includes("water") || s.includes("tea")) return "There's a coffee and water station to the right of the seating area — help yourself while you wait.";
    if (s.includes("late") || s.includes("host") || s.includes("waiting")) return "If your host hasn't come down in 10 minutes, I can re-notify them or escalate to their team. Tap 'Walk-in visitor' and reception can also help.";
    if (s.includes("emergency") || s.includes("fire") || s.includes("evacuat")) return "In an emergency, follow the green exit signs to Assembly Point A in the front courtyard. Staff wardens in orange vests will guide you.";
    if (s.includes("slip") || s.includes("gate pass") || s.includes("paper")) return "If you have a paper gate pass, please go to the reception desk — they'll scan it and confirm with your host before issuing a badge.";
    return "I can help with wifi, parking, restrooms, refreshments, a late host, paper gate passes, or emergencies. For anything else, the receptionist is happy to help. (Demo note: in production this would be a real AI assistant.)";
  };
  const send = () => {
    const q = input.trim(); if (!q) return;
    setInput("");
    setMsgs((m) => [...m, { who: "you", text: q }]);
    setTimeout(() => setMsgs((m) => [...m, { who: "bot", text: reply(q) }]), 500);
  };
  return (
    <div className="absolute bottom-20 right-6 w-72 bg-white border border-slate-300 rounded-xl shadow-lg flex flex-col overflow-hidden z-40">
      <div className="flex items-center justify-between bg-violet-500 text-white px-3 py-2">
        <span className="text-sm flex items-center gap-1.5"><Sparkles size={14} className="text-violet-400" /> Lobby assistant</span>
        <button onClick={onClose} className="text-slate-300 hover:text-white"><X size={15} /></button>
      </div>
      <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
        {msgs.map((m, i) => (
          <div key={i} className={`text-xs leading-relaxed rounded-lg px-2.5 py-2 max-w-[90%] ${m.who === "bot" ? "bg-slate-100 text-slate-700" : "bg-violet-500 text-white ml-auto"}`}>{m.text}</div>
        ))}
      </div>
      <div className="flex border-t border-slate-200">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Ask something…" className="flex-1 px-3 py-2 text-xs outline-none" />
        <button onClick={send} className="px-3 text-violet-500 hover:text-violet-600"><Send size={15} /></button>
      </div>
    </div>
  );
}

/* ================= Reception ================= */
function Reception({ slipEntry, visitors, isOver, addDelivery, deliveries }) {
  const [f, setF] = useState({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0], slipRef: "" });
  const [sent, setSent] = useState(false);
  const [d, setD] = useState({ courier: "", pkg: "", host: HOSTS[0] });
  const logDelivery = () => {
    if (!d.courier.trim() || !d.pkg.trim()) return;
    addDelivery(d);
    setD({ courier: "", pkg: "", host: HOSTS[0] });
  };
  const submit = () => {
    if (!f.name.trim() || !f.slipRef.trim()) return;
    slipEntry(f); setSent(true);
    setF({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0], slipRef: "" });
    setTimeout(() => setSent(false), 4000);
  };
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card>
        <h2 className="text-lg font-semibold text-slate-800 mb-1 flex items-center gap-2"><ClipboardList size={18} /> Paper slip conversion</h2>
        <p className="text-xs text-slate-500 mb-4">Digitize a visitor's paper gate pass. The named host must confirm before a badge is issued — a slip alone never grants entry.</p>
        <div className="space-y-3">
          <label className="text-xs text-slate-500 block">Slip reference
            <input value={f.slipRef} onChange={(e) => setF({ ...f, slipRef: e.target.value })} placeholder="GP-1042" className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" style={mono} />
          </label>
          <label className="text-xs text-slate-500 block">Visitor name (from slip and ID)
            <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Dinesh Kumar" className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs text-slate-500 block">Named host
              <select value={f.host} onChange={(e) => setF({ ...f, host: e.target.value })} className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">{HOSTS.map((h) => <option key={h}>{h}</option>)}</select>
            </label>
            <label className="text-xs text-slate-500 block">Purpose
              <select value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">{PURPOSES.map((p) => <option key={p}>{p}</option>)}</select>
            </label>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500"><Camera size={14} /> Slip photographed and attached · ID checked against slip name</div>
          <button onClick={submit} className="w-full bg-violet-500 text-white text-sm rounded-lg py-2.5 hover:bg-violet-600">Send host confirmation request</button>
          {sent && <p className="text-xs text-emerald-700 flex items-center gap-1"><CheckCircle2 size={14} /> Request sent — approve or deny it in the Host app tab.</p>}
        </div>
      </Card>
      <Card>
        <h2 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2"><Users size={18} /> Today at reception</h2>
        <div className="divide-y divide-slate-100">
          {visitors.slice(0, 7).map((v) => (
            <div key={v.id} className="flex items-center gap-3 py-2.5">
              <Avatar name={v.name} tone={v.vip ? "bg-violet-100 text-violet-800" : "bg-emerald-100 text-emerald-800"} />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{v.name}</p>
                <p className="text-xs text-slate-500 truncate">{v.method} · {v.host.split(" —")[0]} · {fmt(v.checkinAt)}</p>
              </div>
              <StatusPill v={v} isOver={isOver} />
            </div>
          ))}
        </div>
      </Card>
      <Card className="lg:col-span-2">
        <h2 className="text-lg font-semibold text-slate-800 mb-1 flex items-center gap-2"><Package size={18} /> Deliveries and mailroom</h2>
        <p className="text-xs text-slate-500 mb-4">Log a courier package — the recipient is notified instantly and can confirm collection from the Host app.</p>
        <div className="grid sm:grid-cols-4 gap-3 mb-4">
          <input value={d.courier} onChange={(e) => setD({ ...d, courier: e.target.value })} placeholder="Courier (e.g. BlueDart)" className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          <input value={d.pkg} onChange={(e) => setD({ ...d, pkg: e.target.value })} placeholder="Package description" className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          <select value={d.host} onChange={(e) => setD({ ...d, host: e.target.value })} className="border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">{HOSTS.map((h) => <option key={h}>{h}</option>)}</select>
          <button onClick={logDelivery} className="bg-violet-500 text-white text-sm rounded-lg py-2 hover:bg-violet-600">Log and notify</button>
        </div>
        <div className="divide-y divide-slate-100">
          {deliveries.map((dv) => (
            <div key={dv.id} className="flex items-center gap-3 py-2.5">
              <Package size={18} className="text-slate-400 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{dv.pkg} <span className="text-slate-400">from {dv.courier}</span></p>
                <p className="text-xs text-slate-500">For {dv.host.split(" —")[0]} · logged {fmt(dv.at)}</p>
              </div>
              {dv.collected ? <Pill tone="green">Collected</Pill> : <Pill tone="amber">Awaiting pickup</Pill>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ================= Security ================= */
const ZONE_RECTS = {
  lobby: { x: 10, y: 130, w: 200, h: 70 },
  floor2: { x: 10, y: 10, w: 140, h: 110 },
  floor3: { x: 160, y: 10, w: 140, h: 110 },
  hr: { x: 310, y: 10, w: 130, h: 110 },
  basement: { x: 220, y: 130, w: 130, h: 70 },
  mailroom: { x: 360, y: 130, w: 80, h: 70 },
};

function ZoneMap({ onSite, isOver }) {
  const byZone = {};
  onSite.forEach((v) => { (byZone[v.zoneKey] = byZone[v.zoneKey] || []).push(v); });
  return (
    <svg viewBox="0 0 450 210" className="w-full">
      {Object.entries(ZONE_RECTS).map(([k, r]) => (
        <g key={k}>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} rx="8" fill="#fafaf9" stroke="#d6d3d1" strokeWidth="1" />
          <text x={r.x + 10} y={r.y + 18} fontSize="10" fill="#78716c" style={font}>{ZONE_LABEL[k]}</text>
          {(byZone[k] || []).map((v, i) => {
            const cx = r.x + 22 + (i % 4) * 30, cy = r.y + 42 + Math.floor(i / 4) * 26;
            const fill = v.vip ? "#ddd6fe" : isOver(v) ? "#fde68a" : "#a7f3d0";
            const stroke = v.vip ? "#6d28d9" : isOver(v) ? "#b45309" : "#047857";
            return (
              <g key={v.id}>
                <circle cx={cx} cy={cy} r="11" fill={fill} stroke={stroke} strokeWidth="1" />
                <text x={cx} y={cy + 3} fontSize="8" textAnchor="middle" fill={stroke} style={font}>{initials(v.name)}</text>
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

function Security({ visitors, onSite, isOver, alerts, setAlerts, update, evac, setEvac, addAlert, ping }) {
  const out = visitors.filter((v) => v.status === "checked-out").length;
  const active = alerts.filter((a) => !a.reviewed);
  const overs = onSite.filter(isOver);
  const review = (id) => setAlerts((s) => s.map((a) => (a.id === id ? { ...a, reviewed: true } : a)));
  const simulate = () => addAlert({ sev: "danger", title: "Badge and face mismatch — gate A1", detail: "Camera AI: badge V-20455 presented by an unenrolled face. Entry blocked pending review." });
  const minsOn = (v) => Math.max(0, Math.floor((Date.now() - v.checkinAt) / 60000));
  const safe = onSite.filter((v) => v.status === "safe").length;
  const pct = onSite.length ? Math.round((safe / onSite.length) * 100) : 100;

  if (evac) {
    return (
      <Card className="border-rose-300">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
          <h2 className="text-lg font-semibold text-slate-800 flex items-center gap-2 text-rose-700"><Siren size={18} /> Evacuation muster</h2>
          <button onClick={() => setEvac(false)} className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 hover:bg-slate-100">End evacuation</button>
        </div>
        <p className="text-xs text-slate-500 mb-3">Mark each person safe as they reach the assembly point.</p>
        <div className="mb-4">
          <div className="flex justify-between text-xs text-slate-500 mb-1"><span>Accounted for</span><span style={mono}>{safe}/{onSite.length} · {pct}%</span></div>
          <div className="h-2 bg-slate-200 rounded-full overflow-hidden"><div className="h-full bg-emerald-600 rounded-full" style={{ width: `${pct}%`, transition: "width .4s" }} /></div>
        </div>
        {pct === 100 && onSite.length > 0 && <p className="text-sm text-emerald-700 mb-3 flex items-center gap-1"><CheckCircle2 size={16} /> Everyone is accounted for.</p>}
        <div className="divide-y divide-slate-100">
          {onSite.map((v) => (
            <div key={v.id} className="flex items-center gap-3 py-2.5">
              <Avatar name={v.name} />
              <div className="flex-1"><p className="text-sm">{v.name}</p><p className="text-xs text-slate-500">{ZONE_LABEL[v.zoneKey]}</p></div>
              {v.status === "safe" ? <Pill tone="green">Safe</Pill> : (
                <button onClick={() => update(v.id, { status: "safe" })} className="text-xs bg-emerald-500 text-white rounded-lg px-3 py-1.5 hover:bg-emerald-600">Mark safe</button>
              )}
            </div>
          ))}
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[["On site now", onSite.length], ["Expected today", onSite.length + 17], ["Checked out", out + 12], ["Active alerts", active.length + overs.length, active.length + overs.length > 0]].map(([label, val, danger]) => (
          <div key={label} className="bg-white border border-slate-200 rounded-xl p-4">
            <p className="text-xs text-slate-500 mb-1">{label}</p>
            <p className={`text-2xl font-medium ${danger ? "text-rose-600" : ""}`} style={mono}>{val}</p>
          </div>
        ))}
      </div>

      <Card>
        <h2 className="text-sm font-semibold text-slate-800 mb-2 flex items-center gap-2"><MapPin size={16} /> Live zone map</h2>
        <ZoneMap onSite={onSite} isOver={isOver} />
        <p className="text-xs text-slate-400 mt-1">Green = checked in · amber = overstay · violet = VIP. Positions update as visitors check in and out.</p>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2"><BarChart3 size={16} /> Visitor traffic today</h2>
        <div className="flex items-end gap-2 h-28">
          {[["9a", 4], ["10a", 9], ["11a", 12], ["12p", 7], ["1p", 5], ["2p", 11], ["3p", Math.max(3, onSite.length)], ["4p", 0], ["5p", 0]].map(([h, n], i) => (
            <div key={h} className="flex-1 flex flex-col items-center gap-1">
              <span className="text-xs text-slate-500" style={mono}>{n > 0 ? n : ""}</span>
              <div className={`w-full rounded-t ${i === 6 ? "bg-emerald-600" : n > 0 ? "bg-slate-300" : "bg-slate-100"}`} style={{ height: `${Math.max(4, n * 7)}px` }} />
              <span className="text-xs text-slate-400">{h}</span>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-2">Green bar = current hour (live count). Peak so far: 11 am. Predicted evening peak: 4–5 pm (AI forecast, demo data).</p>
      </Card>

      <Card>
        <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
          <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2"><Camera size={16} /> AI camera alerts</h2>
          <div className="flex gap-2">
            <button onClick={simulate} className="text-xs border border-slate-300 rounded-lg px-3 py-1.5 hover:bg-slate-100">Simulate camera event</button>
            <button onClick={() => setEvac(true)} className="text-xs bg-rose-600 text-white rounded-lg px-3 py-1.5 hover:bg-rose-500 flex items-center gap-1"><Siren size={13} /> Start evacuation</button>
          </div>
        </div>
        {active.length === 0 && overs.length === 0 && <p className="text-sm text-slate-400">No active alerts.</p>}
        <div className="space-y-2">
          {overs.map((v) => (
            <div key={`o${v.id}`} className="flex items-center gap-3 rounded-lg px-3 py-2.5 bg-amber-50">
              <Clock size={18} className="text-amber-700 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-amber-800">Overstay — {v.name} · badge {v.badge}</p>
                <p className="text-xs text-amber-700">On site {minsOn(v)} min, window was {v.windowMins} min. Host notified.</p>
              </div>
            </div>
          ))}
          {active.map((a) => (
            <div key={a.id} className="flex items-center gap-3 rounded-lg px-3 py-2.5 bg-rose-50">
              <AlertTriangle size={18} className="text-rose-700 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-rose-800">{a.title}</p>
                <p className="text-xs text-rose-700">{a.detail} · {fmt(a.at)}</p>
              </div>
              <button onClick={() => review(a.id)} className="text-xs border border-slate-300 bg-white rounded-lg px-3 py-1.5 hover:bg-slate-100">Review</button>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-slate-800 mb-3 flex items-center gap-2"><Users size={16} /> On site now</h2>
        <div className="divide-y divide-slate-100">
          {onSite.map((v) => (
            <div key={v.id} className="flex items-center gap-3 py-2.5">
              <Avatar name={v.name} tone={v.vip ? "bg-violet-100 text-violet-800" : isOver(v) ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"} />
              <div className="flex-1 min-w-0">
                <p className="text-sm truncate">{v.name}</p>
                <p className="text-xs text-slate-500 truncate">{ZONE_LABEL[v.zoneKey]} · badge <span style={mono}>{v.badge}</span> · {minsOn(v)} min on site · {v.hostResponse ? `host: ${v.hostResponse.toLowerCase()}` : "host not yet responded"}</p>
              </div>
              <StatusPill v={v} isOver={isOver} />
              <button onClick={() => { update(v.id, { status: "checked-out" }); ping(`${v.name} checked out — badge ${v.badge} deactivated`); }} className="text-xs border border-slate-300 rounded-lg px-2.5 py-1.5 hover:bg-slate-100 flex items-center gap-1"><LogOut size={12} /> Out</button>
            </div>
          ))}
          {onSite.length === 0 && <p className="text-sm text-slate-400 py-2">Nobody on site.</p>}
        </div>
      </Card>
    </div>
  );
}

/* ================= Host app ================= */
function HostApp({ pending, recent, hostAct, createInvite, invites, deliveries, markCollected }) {
  const [inv, setInv] = useState({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0] });
  const [made, setMade] = useState(null);
  const arrivals = pending.filter((v) => v.status === "checked-in");
  const approvals = pending.filter((v) => v.status === "awaiting-approval");
  const held = pending.filter((v) => v.status === "held");
  const history = recent.filter((v) => v.hostResponse && v.status !== "awaiting-approval").slice(0, 4);
  const make = () => {
    if (!inv.name.trim()) return;
    createInvite(inv);
    setMade(inv.name);
    setInv({ name: "", company: "", host: HOSTS[0], purpose: PURPOSES[0] });
    setTimeout(() => setMade(null), 4000);
  };
  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-lg font-semibold text-slate-800 mb-1 flex items-center gap-2"><CalendarPlus size={18} /> Pre-register a visitor</h2>
        <p className="text-xs text-slate-500 mb-4">Creates an invite with a QR pass. Then go to the Kiosk tab, tap "Scan QR invite", and check them in with it.</p>
        <div className="space-y-3">
          <input value={inv.name} onChange={(e) => setInv({ ...inv, name: e.target.value })} placeholder="Visitor full name" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          <input value={inv.company} onChange={(e) => setInv({ ...inv, company: e.target.value })} placeholder="Company (optional)" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          <div className="grid grid-cols-2 gap-3">
            <select value={inv.host} onChange={(e) => setInv({ ...inv, host: e.target.value })} className="border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">{HOSTS.map((h) => <option key={h}>{h}</option>)}</select>
            <select value={inv.purpose} onChange={(e) => setInv({ ...inv, purpose: e.target.value })} className="border border-slate-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500">{PURPOSES.map((p) => <option key={p}>{p}</option>)}</select>
          </div>
          <button onClick={make} className="w-full bg-violet-500 text-white text-sm rounded-lg py-2.5 hover:bg-violet-600">Send invite with QR pass</button>
          {made && <p className="text-xs text-emerald-700 flex items-center gap-1"><CheckCircle2 size={14} /> Invite sent to {made} — now try it at the Kiosk.</p>}
        </div>
        <div className="mt-4 border-t border-slate-100 pt-3">
          <p className="text-xs font-medium text-slate-500 mb-2">Open invites</p>
          {invites.filter((i) => !i.used).map((i) => (
            <div key={i.id} className="flex items-center justify-between text-xs py-1.5">
              <span>{i.name} <span className="text-slate-400">· {i.purpose.toLowerCase()}</span></span>
              <span className="text-slate-500" style={mono}>{i.ref}</span>
            </div>
          ))}
          {invites.filter((i) => !i.used).length === 0 && <p className="text-xs text-slate-400">None — all invites used.</p>}
        </div>
      </Card>

      <div className="space-y-3">
        <p className="text-xs text-slate-500">Arrivals, approvals, and deliveries land here as push notifications.</p>
        {pending.length === 0 && deliveries.filter((dv) => !dv.collected).length === 0 && <Card className="text-center text-sm text-slate-400">No pending notifications. Check someone in at the kiosk or send a slip request from reception.</Card>}

        {deliveries.filter((dv) => !dv.collected).map((dv) => (
          <Card key={`d${dv.id}`} className="border-slate-300">
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2"><Package size={14} /> Package at reception · {fmt(dv.at)}</div>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-full bg-slate-200 flex items-center justify-center shrink-0"><Package size={16} className="text-slate-600" /></div>
              <div><p className="text-sm font-medium">{dv.pkg}</p><p className="text-xs text-slate-500">From {dv.courier} · waiting at the front desk</p></div>
            </div>
            <button onClick={() => markCollected(dv.id)} className="w-full text-sm border border-slate-300 rounded-lg py-2 hover:bg-slate-100">Mark as collected</button>
          </Card>
        ))}

        {approvals.map((v) => {
          const isSlip = v.method.startsWith("Paper slip");
          return (
            <Card key={v.id} className="border-amber-300">
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">{isSlip ? <ClipboardList size={14} /> : <UserPlus size={14} />} {isSlip ? "Paper slip confirmation" : "Walk-in approval request"} · now</div>
              <div className="flex items-center gap-3 mb-2">
                <Avatar name={v.name} tone="bg-amber-100 text-amber-800" />
                <div><p className="text-sm font-medium">{v.name} is at {isSlip ? "reception" : "the lobby kiosk"}</p><p className="text-xs text-slate-500">{isSlip ? `${v.method} · claims your approval` : "No prior invite · photo and NDA captured"} · {v.purpose.toLowerCase()}</p></div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => hostAct(v, "Approve slip")} className="text-sm bg-emerald-500 text-white rounded-lg py-2 hover:bg-emerald-600 flex items-center justify-center gap-1"><UserCheck size={14} /> Confirm</button>
                <button onClick={() => hostAct(v, "Deny")} className="text-sm border border-rose-300 text-rose-700 rounded-lg py-2 hover:bg-rose-50 flex items-center justify-center gap-1"><UserX size={14} /> Deny</button>
              </div>
            </Card>
          );
        })}

        {arrivals.map((v) => (
          <Card key={v.id}>
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-2"><Bell size={14} /> Visitor arrival · {fmt(v.checkinAt)}</div>
            <div className="flex items-center gap-3 mb-2">
              <Avatar name={v.name} />
              <div><p className="text-sm font-medium">{v.name} has arrived</p><p className="text-xs text-slate-500">{v.company} · main lobby · badge <span style={mono}>{v.badge}</span></p></div>
            </div>
            <p className="text-xs text-slate-500 border-t border-slate-100 pt-2 mb-3">{v.purpose} · NDA signed · escort not required</p>
            <div className="grid grid-cols-2 gap-2">
              {["On my way", "Delay 10 min", "Delegate to Sara"].map((a) => (
                <button key={a} onClick={() => hostAct(v, a)} className="text-sm border border-slate-300 rounded-lg py-2 hover:bg-slate-100">{a}</button>
              ))}
              <button onClick={() => hostAct(v, "Deny")} className="text-sm border border-rose-300 text-rose-700 rounded-lg py-2 hover:bg-rose-50">Deny</button>
            </div>
          </Card>
        ))}

        {held.map((v) => (
          <Card key={v.id} className="border-rose-300">
            <div className="flex items-center gap-2 text-xs text-rose-700 mb-1"><ShieldAlert size={14} /> Security hold</div>
            <p className="text-sm">{v.name} was flagged at the kiosk and is being reviewed by security. You'll be notified when it's resolved.</p>
          </Card>
        ))}

        {history.length > 0 && (
          <Card>
            <p className="text-xs font-medium text-slate-500 mb-2">Earlier today</p>
            <div className="divide-y divide-slate-100">
              {history.map((v) => (
                <div key={v.id} className="flex items-center justify-between py-2 text-xs">
                  <span>{v.name}</span><span className="text-slate-400">{v.hostResponse}</span>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

/* ================= Admin ================= */
function Admin({ watchlist, setWatchlist }) {
  const [name, setName] = useState("");
  const add = () => { if (name.trim()) { setWatchlist((s) => [...s, name.trim()]); setName(""); } };
  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <Card>
        <h2 className="text-lg font-semibold text-slate-800 mb-1 flex items-center gap-2"><Eye size={18} /> Watchlist</h2>
        <p className="text-xs text-slate-500 mb-4">Names here are held at the kiosk for security review. Add one, then check in with it on the Kiosk tab.</p>
        <div className="flex gap-2 mb-4">
          <input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Full name" className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/40 focus:border-violet-500" />
          <button onClick={add} className="text-sm bg-violet-500 text-white rounded-lg px-4 hover:bg-violet-600">Add</button>
        </div>
        <div className="space-y-2">
          {watchlist.map((w) => (
            <div key={w} className="flex items-center justify-between bg-rose-50 rounded-lg px-3 py-2">
              <span className="text-sm text-rose-800">{w}</span>
              <button onClick={() => setWatchlist((s) => s.filter((x) => x !== w))} className="text-xs text-rose-700 hover:underline">Remove</button>
            </div>
          ))}
          {watchlist.length === 0 && <p className="text-sm text-slate-400">Watchlist is empty.</p>}
        </div>
      </Card>
      <Card>
        <h2 className="text-lg font-semibold text-slate-800 mb-3 flex items-center gap-2"><Settings size={18} /> Zone policies</h2>
        <div className="space-y-2 text-sm">
          {PURPOSES.map((purpose) => (
            <div key={purpose} className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2.5">
              <div><p>{purpose}</p><p className="text-xs text-slate-500">{ZONE_LABEL[ZONE_OF[purpose]]}</p></div>
              <Pill tone={purpose === "Contractor work" ? "amber" : "gray"}>{purpose === "Contractor work" ? "PPE required" : "Standard"}</Pill>
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-400 mt-4">Badges auto-expire at the end of the visit window or on checkout. Camera AI (tailgating, badge-face match) is enabled — see the simulate button in Security.</p>
      </Card>
    </div>
  );
}
