import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Activity, Wifi, WifiOff, Users, Shield, AlertTriangle, Clock,
  Eye, Monitor, Smartphone, Router, HelpCircle, ChevronDown,
  ChevronRight, BarChart3, Brain, Home, Heart, Zap, Globe,
  Lock, Radio, Fingerprint, TrendingUp, Search, RefreshCw
} from "lucide-react";

// ─── Seed Data ───────────────────────────────────────────────
const SEED_DATA = {
  timestamp: "2026-03-26T10:08:28",
  scan_count: 3,
  device_count: 10,
  device_profiles: {
    "f8-bb-bf-59-c2-d2": { mac: "f8-bb-bf-59-c2-d2", ip: "192.168.7.1", manufacturer: "Arris/CommScope (ISP Router)", randomized_mac: false, category: "infrastructure", category_confidence: 0.95, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: null },
    "f2-86-37-40-ff-5b": { mac: "f2-86-37-40-ff-5b", ip: "192.168.7.20", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 0 },
    "4a-42-35-da-ee-6f": { mac: "4a-42-35-da-ee-6f", ip: "192.168.7.21", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 1 },
    "9c-3d-cf-8e-5d-81": { mac: "9c-3d-cf-8e-5d-81", ip: "192.168.7.23", manufacturer: "NETGEAR", randomized_mac: false, category: "infrastructure", category_confidence: 0.80, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: null },
    "50-14-79-4a-d3-02": { mac: "50-14-79-4a-d3-02", ip: "192.168.7.24", manufacturer: "Liteon/Apple (Mac/iPhone/iPad)", randomized_mac: false, category: "personal_device", category_confidence: 0.60, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 2 },
    "22-72-9b-d4-a4-c9": { mac: "22-72-9b-d4-a4-c9", ip: "192.168.7.28", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 0.67, scan_count: 2, currently_present: true, cluster_id: 3 },
    "b2-80-d1-bf-bd-81": { mac: "b2-80-d1-bf-bd-81", ip: "192.168.7.30", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 4 },
    "32-96-f3-24-ea-07": { mac: "32-96-f3-24-ea-07", ip: "192.168.7.31", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 5 },
    "76-96-3a-72-8b-bf": { mac: "76-96-3a-72-8b-bf", ip: "192.168.7.33", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 0.33, scan_count: 1, currently_present: false, cluster_id: 6 },
    "ae-06-40-be-94-a5": { mac: "ae-06-40-be-94-a5", ip: "192.168.7.36", manufacturer: "Randomized MAC", randomized_mac: true, category: "personal_mobile", category_confidence: 0.85, presence_ratio: 1.0, scan_count: 3, currently_present: true, cluster_id: 7 },
  },
  clusters: [],
  household: {
    location: "family_farm",
    expected_residents: 4,
    inferred_resident_count: 0,
    infrastructure_devices: 2,
    personal_devices: 8,
    confidence_note: "Early data (3 scans). Accuracy improves after 50+ scans over several days.",
    residents_context: [
      { name: "Chris", role: "son", tech_savvy: true, permanent: false },
      { name: "Dad", role: "patriarch", elderly: true, permanent: true, fall_risk: true },
      { name: "Mom", role: "matriarch", elderly: true, permanent: true, fall_risk: true },
      { name: "Katie", role: "twin_sister", permanent: false },
    ],
  },
  inferences: [
    { type: "infrastructure_id", confidence: 0.85, text: "Infrastructure identified: Xfinity Gateway (.1) and NETGEAR device (.23)" },
    { type: "privacy_macs", confidence: 0.90, text: "7 devices using randomized MACs — modern phones/tablets with WiFi privacy" },
    { type: "data_advisory", confidence: 1.0, text: "3 scans recorded. Need 50+ scans for reliable person-clustering." },
  ],
  defense: {
    last_check: "2026-03-26T10:15:00",
    status: "secure",
    checks_passed: 7,
    checks_total: 7,
    gateway_mac_locked: "f8-bb-bf-59-c2-d2",
    dns_integrity: "verified",
  },
  travel: {
    mode: "home",
    network_name: "Cimino Farm",
    fingerprint_id: "da21907d",
  },
};

// ─── Theme & Style Constants ──────────────────────────────────
const CAT = {
  infrastructure:           { accent: "#64748b", bg: "rgba(51,65,85,0.35)", label: "Infrastructure", Icon: Router },
  personal_mobile:          { accent: "#3b82f6", bg: "rgba(37,99,235,0.18)", label: "Personal Mobile", Icon: Smartphone },
  personal_device:          { accent: "#8b5cf6", bg: "rgba(109,40,217,0.18)", label: "Personal Device", Icon: Monitor },
  communal_or_resident:     { accent: "#f59e0b", bg: "rgba(245,158,11,0.18)", label: "Communal", Icon: Users },
  visitor_or_intermittent:  { accent: "#ec4899", bg: "rgba(236,72,153,0.18)", label: "Visitor", Icon: Eye },
  unclassified:             { accent: "#6b7280", bg: "rgba(107,114,128,0.18)", label: "Unknown", Icon: HelpCircle },
};

function getCat(category) {
  return CAT[category] || CAT.unclassified;
}

// ─── Utility Components ───────────────────────────────────────

function Pill({ children, color = "#3b82f6", size = "sm" }) {
  const pad = size === "xs" ? "px-1.5 py-0.5 text-xs" : "px-2 py-0.5 text-xs";
  return (
    <span className={`${pad} rounded-full font-medium inline-flex items-center gap-1`}
          style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}>
      {children}
    </span>
  );
}

function ProgressRing({ value, size = 40, stroke = 3, color = "#10b981" }) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.min(1, Math.max(0, value)));
  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1e293b" strokeWidth={stroke} />
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
              strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
              style={{ transition: "stroke-dashoffset 0.6s ease" }} />
    </svg>
  );
}

function StatCard({ icon: Icon, label, value, sub, accent = "#10b981" }) {
  return (
    <div className="rounded-xl p-4" style={{ background: "rgba(15,23,42,0.7)", border: "1px solid rgba(148,163,184,0.1)" }}>
      <div className="flex items-center gap-2 mb-2">
        <div className="p-1.5 rounded-lg" style={{ background: `${accent}18` }}>
          <Icon size={16} style={{ color: accent }} />
        </div>
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title, accent = "#94a3b8", children }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <div className="flex items-center gap-2">
        <Icon size={18} style={{ color: accent }} />
        <h2 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">{title}</h2>
      </div>
      {children}
    </div>
  );
}

// ─── Device Row ───────────────────────────────────────────────

function DeviceRow({ device, expanded, onToggle }) {
  const cat = getCat(device.category);
  const CatIcon = cat.Icon;
  const conf = Math.round(device.category_confidence * 100);
  const present = device.currently_present;

  return (
    <div className="rounded-lg overflow-hidden transition-all duration-200"
         style={{ background: expanded ? cat.bg : "rgba(15,23,42,0.5)", border: `1px solid ${expanded ? cat.accent + "44" : "rgba(148,163,184,0.08)"}` }}>
      <div className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:brightness-110 transition"
           onClick={onToggle}>
        {/* Status dot */}
        <div className="w-2 h-2 rounded-full flex-shrink-0"
             style={{ background: present ? "#10b981" : "#ef4444", boxShadow: present ? "0 0 6px #10b98166" : "none" }} />
        {/* Icon */}
        <div className="p-1.5 rounded-md flex-shrink-0" style={{ background: `${cat.accent}18` }}>
          <CatIcon size={15} style={{ color: cat.accent }} />
        </div>
        {/* Name & Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-100 font-mono">{device.ip}</span>
            {device.randomized_mac && (
              <Pill color="#f59e0b" size="xs"><Fingerprint size={10} /> Private</Pill>
            )}
          </div>
          <div className="text-xs text-slate-500 truncate">{device.manufacturer}</div>
        </div>
        {/* Cluster badge */}
        {device.cluster_id !== null && (
          <Pill color={cat.accent}>P{device.cluster_id + 1}</Pill>
        )}
        {/* Confidence mini-bar */}
        <div className="w-12 flex-shrink-0">
          <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${conf}%`, background: conf > 70 ? "#10b981" : conf > 40 ? "#f59e0b" : "#ef4444" }} />
          </div>
          <div className="text-center text-xs text-slate-600 mt-0.5">{conf}%</div>
        </div>
        {/* Expand chevron */}
        {expanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-600" />}
      </div>

      {/* Expanded detail panel */}
      {expanded && (
        <div className="px-4 pb-3 pt-1 border-t" style={{ borderColor: `${cat.accent}22` }}>
          <div className="grid grid-cols-3 gap-x-4 gap-y-2 text-xs">
            <Detail label="MAC" value={device.mac} mono />
            <Detail label="Category" value={cat.label} color={cat.accent} />
            <Detail label="Scans seen" value={`${device.scan_count} of ${SEED_DATA.scan_count}`} />
            <Detail label="Presence" value={`${(device.presence_ratio * 100).toFixed(0)}%`} />
            <Detail label="MAC type" value={device.randomized_mac ? "Randomized (privacy)" : "Global (fixed)"} color={device.randomized_mac ? "#f59e0b" : "#64748b"} />
            {device.cluster_id !== null && <Detail label="Person cluster" value={`Person ${device.cluster_id + 1}`} color="#06b6d4" />}
          </div>
        </div>
      )}
    </div>
  );
}

function Detail({ label, value, color, mono }) {
  return (
    <div>
      <span className="text-slate-600">{label}: </span>
      <span className={mono ? "font-mono" : ""} style={{ color: color || "#cbd5e1" }}>{value}</span>
    </div>
  );
}

// ─── Inference Item ───────────────────────────────────────────

function InferenceItem({ inference }) {
  const colors = {
    infrastructure_id: "#64748b",
    privacy_macs: "#f59e0b",
    device_cluster: "#06b6d4",
    strong_cooccurrence: "#10b981",
    always_present: "#8b5cf6",
    data_advisory: "#3b82f6",
    routine_pattern: "#ec4899",
    household_assignment: "#f97316",
  };
  const c = colors[inference.type] || "#6b7280";
  const conf = Math.round(inference.confidence * 100);

  return (
    <div className="flex items-start gap-3 rounded-lg px-3 py-2.5"
         style={{ background: "rgba(15,23,42,0.5)", borderLeft: `3px solid ${c}` }}>
      <Brain size={14} style={{ color: c, marginTop: 2, flexShrink: 0 }} />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-300 leading-snug">{inference.text}</p>
      </div>
      <span className="text-xs font-mono flex-shrink-0" style={{ color: c }}>{conf}%</span>
    </div>
  );
}

// ─── Household Card ───────────────────────────────────────────

function ResidentChip({ resident }) {
  const isFallRisk = resident.fall_risk;
  const isElderly = resident.elderly;
  const accent = isFallRisk ? "#ef4444" : isElderly ? "#f59e0b" : "#10b981";

  return (
    <div className="flex items-center gap-2 rounded-lg px-3 py-2"
         style={{ background: `${accent}0d`, border: `1px solid ${accent}33` }}>
      <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold"
           style={{ background: `${accent}22`, color: accent }}>
        {resident.name[0]}
      </div>
      <div className="flex-1">
        <div className="text-sm font-medium text-slate-200">{resident.name}</div>
        <div className="text-xs text-slate-500 capitalize">{resident.role.replace(/_/g, " ")}</div>
      </div>
      <div className="flex gap-1">
        {isFallRisk && <Pill color="#ef4444" size="xs"><Heart size={9} /> Fall risk</Pill>}
        {resident.tech_savvy && <Pill color="#10b981" size="xs"><Zap size={9} /> Tech</Pill>}
        {resident.permanent && <Pill color="#64748b" size="xs"><Home size={9} /></Pill>}
      </div>
    </div>
  );
}

// ─── Defense Status Bar ───────────────────────────────────────

function DefenseBar({ defense, travel }) {
  if (!defense) return null;
  const secure = defense.status === "secure";
  const statusColor = secure ? "#10b981" : "#ef4444";
  const modeLabel = travel?.mode === "home" ? travel.network_name || "Home" : "Travel";

  return (
    <div className="flex items-center gap-4 rounded-xl px-4 py-3 mb-4"
         style={{ background: "rgba(15,23,42,0.8)", border: `1px solid ${statusColor}33` }}>
      <div className="flex items-center gap-2">
        <Shield size={18} style={{ color: statusColor }} />
        <span className="text-sm font-semibold" style={{ color: statusColor }}>
          {secure ? "Secure" : "Alert"}
        </span>
      </div>
      <div className="h-4 w-px bg-slate-700" />
      <div className="flex items-center gap-4 text-xs text-slate-400">
        <span>{defense.checks_passed}/{defense.checks_total} checks passed</span>
        <span className="flex items-center gap-1"><Lock size={11} /> DNS {defense.dns_integrity}</span>
        <span className="flex items-center gap-1"><Radio size={11} /> GW MAC locked</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Pill color={travel?.mode === "home" ? "#10b981" : "#f59e0b"} size="xs">
          <Globe size={10} /> {modeLabel}
        </Pill>
        <span className="text-xs text-slate-600 font-mono">{travel?.fingerprint_id}</span>
      </div>
    </div>
  );
}

// ─── Data Collection Progress ─────────────────────────────────

function LearningProgress({ scanCount }) {
  const milestones = [
    { label: "MAC ID", target: 10, desc: "Identifying randomized vs global MACs" },
    { label: "Classification", target: 50, desc: "Sorting infrastructure vs personal" },
    { label: "Clustering", target: 200, desc: "Grouping devices into person-clusters" },
    { label: "Routines", target: 672, desc: "Full week of behavioral patterns" },
  ];

  return (
    <div className="rounded-xl p-4" style={{ background: "rgba(15,23,42,0.7)", border: "1px solid rgba(148,163,184,0.08)" }}>
      <SectionHeader icon={TrendingUp} title="Learning Progress" accent="#8b5cf6" />
      <div className="space-y-3">
        {milestones.map(m => {
          const pct = Math.min(1, scanCount / m.target);
          const done = pct >= 1;
          return (
            <div key={m.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium" style={{ color: done ? "#10b981" : "#94a3b8" }}>{m.label}</span>
                <span className="text-xs font-mono text-slate-600">{scanCount}/{m.target}</span>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full rounded-full transition-all duration-700"
                     style={{ width: `${pct * 100}%`, background: done ? "#10b981" : `linear-gradient(90deg, #8b5cf6, #3b82f6)` }} />
              </div>
              <div className="text-xs text-slate-600 mt-0.5">{m.desc}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Category Summary ─────────────────────────────────────────

function CategoryBreakdown({ devices }) {
  const counts = {};
  Object.values(devices).forEach(d => {
    const c = d.category || "unclassified";
    counts[c] = (counts[c] || 0) + 1;
  });

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="flex gap-1 h-3 rounded-full overflow-hidden bg-slate-800">
      {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([cat, count]) => {
        const { accent } = getCat(cat);
        const pct = (count / total) * 100;
        return (
          <div key={cat} className="h-full transition-all duration-500 first:rounded-l-full last:rounded-r-full"
               style={{ width: `${pct}%`, background: accent, minWidth: count > 0 ? 4 : 0 }}
               title={`${getCat(cat).label}: ${count}`} />
        );
      })}
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────

export default function PresenceDashboard() {
  const [data] = useState(SEED_DATA);
  const [expandedDevice, setExpandedDevice] = useState(null);
  const [filter, setFilter] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");

  const devices = useMemo(() => {
    let list = Object.values(data.device_profiles);
    if (filter !== "all") list = list.filter(d => d.category === filter);
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      list = list.filter(d => d.ip.includes(q) || d.mac.includes(q) || d.manufacturer.toLowerCase().includes(q));
    }
    return list.sort((a, b) => {
      if (a.currently_present !== b.currently_present) return a.currently_present ? -1 : 1;
      return a.ip.localeCompare(b.ip, undefined, { numeric: true });
    });
  }, [data, filter, searchTerm]);

  const stats = useMemo(() => {
    const all = Object.values(data.device_profiles);
    return {
      total: all.length,
      online: all.filter(d => d.currently_present).length,
      personal: all.filter(d => d.category?.startsWith("personal")).length,
      infra: all.filter(d => d.category === "infrastructure").length,
      unknown: all.filter(d => !d.category || d.category === "unclassified").length,
      clusters: new Set(all.map(d => d.cluster_id).filter(c => c !== null)).size,
    };
  }, [data]);

  const categories = useMemo(() => {
    const cats = new Set(Object.values(data.device_profiles).map(d => d.category));
    return ["all", ...Array.from(cats)];
  }, [data]);

  const now = new Date(data.timestamp);
  const timeStr = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  const dateStr = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

  return (
    <div className="min-h-screen text-slate-100" style={{ background: "linear-gradient(135deg, #0c1222 0%, #0f172a 50%, #111827 100%)" }}>
      {/* ── Header ── */}
      <div className="px-6 pt-5 pb-4" style={{ borderBottom: "1px solid rgba(148,163,184,0.08)" }}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl" style={{ background: "linear-gradient(135deg, #3b82f6, #8b5cf6)" }}>
              <Activity size={22} className="text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white tracking-tight">Presence Intelligence</h1>
              <p className="text-xs text-slate-500">Cimino Farm — Network Behavioral Analysis</p>
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm font-mono text-slate-300">{timeStr}</div>
            <div className="text-xs text-slate-600">{dateStr} — Scan #{data.scan_count}</div>
          </div>
        </div>
      </div>

      <div className="px-6 py-4 space-y-4">
        {/* ── Defense Bar ── */}
        <DefenseBar defense={data.defense} travel={data.travel} />

        {/* ── Stats Row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard icon={Wifi} label="Online" value={stats.online} sub={`of ${stats.total} total`} accent="#10b981" />
          <StatCard icon={Smartphone} label="Personal" value={stats.personal} sub="mobiles & devices" accent="#3b82f6" />
          <StatCard icon={Router} label="Infra" value={stats.infra} sub="routers & APs" accent="#64748b" />
          <StatCard icon={Users} label="Clusters" value={stats.clusters || "—"} sub="person groups" accent="#06b6d4" />
          <StatCard icon={Eye} label="Unknown" value={stats.unknown || 0} sub="unclassified" accent={stats.unknown ? "#ef4444" : "#10b981"} />
          <StatCard icon={BarChart3} label="Scans" value={data.scan_count} sub="data points" accent="#8b5cf6" />
        </div>

        {/* ── Category Breakdown Bar ── */}
        <CategoryBreakdown devices={data.device_profiles} />

        {/* ── Main Grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* ── Left: Device List ── */}
          <div className="lg:col-span-2 space-y-3">
            {/* Filter & Search */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg" style={{ background: "rgba(15,23,42,0.7)" }}>
                <Search size={13} className="text-slate-500" />
                <input type="text" placeholder="Filter devices..." value={searchTerm}
                       onChange={e => setSearchTerm(e.target.value)}
                       className="bg-transparent text-xs text-slate-300 outline-none w-28 placeholder-slate-600" />
              </div>
              {categories.map(c => (
                <button key={c} onClick={() => setFilter(c)}
                        className="text-xs px-2.5 py-1 rounded-md transition font-medium"
                        style={{
                          background: filter === c ? (c === "all" ? "#3b82f622" : `${getCat(c).accent}22`) : "transparent",
                          color: filter === c ? (c === "all" ? "#60a5fa" : getCat(c).accent) : "#64748b",
                          border: `1px solid ${filter === c ? (c === "all" ? "#3b82f644" : `${getCat(c).accent}44`) : "transparent"}`,
                        }}>
                  {c === "all" ? "All" : getCat(c).label}
                </button>
              ))}
            </div>

            {/* Device list */}
            <div className="space-y-1.5">
              {devices.map(d => (
                <DeviceRow key={d.mac} device={d}
                           expanded={expandedDevice === d.mac}
                           onToggle={() => setExpandedDevice(expandedDevice === d.mac ? null : d.mac)} />
              ))}
              {devices.length === 0 && (
                <div className="text-center py-8 text-slate-600 text-sm">No devices match filter</div>
              )}
            </div>
          </div>

          {/* ── Right Sidebar ── */}
          <div className="space-y-4">
            {/* Household */}
            <div className="rounded-xl p-4" style={{ background: "rgba(15,23,42,0.7)", border: "1px solid rgba(148,163,184,0.08)" }}>
              <SectionHeader icon={Home} title="Household" accent="#f59e0b" />
              <div className="space-y-2">
                {data.household.residents_context.map(r => (
                  <ResidentChip key={r.name} resident={r} />
                ))}
              </div>
              <div className="mt-3 pt-3" style={{ borderTop: "1px solid rgba(148,163,184,0.08)" }}>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="text-slate-500">Location</div>
                  <div className="text-slate-300 capitalize">{data.household.location.replace(/_/g, " ")}</div>
                  <div className="text-slate-500">Expected</div>
                  <div className="text-slate-300">{data.household.expected_residents} residents</div>
                  <div className="text-slate-500">Personal devices</div>
                  <div className="text-slate-300">{data.household.personal_devices}</div>
                </div>
              </div>
            </div>

            {/* Inferences */}
            <div className="rounded-xl p-4" style={{ background: "rgba(15,23,42,0.7)", border: "1px solid rgba(148,163,184,0.08)" }}>
              <SectionHeader icon={Brain} title="Inferences" accent="#06b6d4" />
              <div className="space-y-2">
                {data.inferences.map((inf, i) => (
                  <InferenceItem key={i} inference={inf} />
                ))}
                {data.inferences.length === 0 && (
                  <div className="text-sm text-slate-600 text-center py-4">Collecting data...</div>
                )}
              </div>
            </div>

            {/* Learning Progress */}
            <LearningProgress scanCount={data.scan_count} />

            {/* Confidence note */}
            {data.household.confidence_note && (
              <div className="rounded-lg px-3 py-2.5 text-xs text-slate-500 leading-relaxed"
                   style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)" }}>
                <AlertTriangle size={12} className="inline mr-1 text-blue-400" style={{ verticalAlign: "middle" }} />
                {data.household.confidence_note}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
