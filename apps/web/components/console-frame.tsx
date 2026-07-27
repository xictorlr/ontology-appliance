"use client";

import {
  Bell,
  BookOpenCheck,
  Boxes,
  Braces,
  ChevronDown,
  CircleUserRound,
  Database,
  FileClock,
  GitPullRequestArrow,
  LayoutDashboard,
  Menu,
  Network,
  Search,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useState } from "react";
import type { SessionIdentity } from "@/lib/server-auth";

const navigation = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/sources", label: "Sources", icon: Database },
  { href: "/model", label: "Semantic model", icon: Network },
  { href: "/proposals", label: "Review queue", icon: GitPullRequestArrow, count: "3" },
  { href: "/versions", label: "Versions", icon: Boxes },
  { href: "/playground", label: "Gateway", icon: Braces },
  { href: "/traces", label: "Trace & audit", icon: FileClock },
];

export function ConsoleFrame({ identity, children }: { identity: SessionIdentity; children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  async function signOut() {
    await fetch("/api/session", { method: "DELETE" });
    router.replace("/login");
    router.refresh();
  }

  const activeItem = navigation.find((item) => pathname.startsWith(item.href));

  return (
    <div className="console-shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="sidebar-head">
          <Link href="/dashboard" className="brand-lockup" aria-label="Ontology Appliance home">
            <span className="brand-mark"><Network size={20} strokeWidth={1.8} /></span>
            <span><strong>Ontology</strong><small>Appliance</small></span>
          </Link>
          <button className="icon-button mobile-close" onClick={() => setMenuOpen(false)} aria-label="Close navigation"><X size={19} /></button>
        </div>

        <div className="tenant-card">
          <div className="tenant-monogram">DB</div>
          <div><span>Active tenant</span><strong>Demo Bank EU</strong></div>
          <ChevronDown size={15} />
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          <span className="nav-label">Control plane</span>
          {navigation.map(({ href, label, icon: Icon, count }) => (
            <Link key={href} href={href} className={pathname.startsWith(href) ? "active" : ""} onClick={() => setMenuOpen(false)}>
              <Icon size={18} strokeWidth={1.8} />
              <span>{label}</span>
              {count && <em>{count}</em>}
            </Link>
          ))}
          <span className="nav-label secondary-label">Workspace</span>
          <Link href="/settings" className={pathname.startsWith("/settings") ? "active" : ""} onClick={() => setMenuOpen(false)}><Settings size={18} /><span>Settings</span></Link>
          <a href="/api/openapi" target="_blank"><BookOpenCheck size={18} /><span>API contract</span></a>
        </nav>

        <div className="sidebar-principle">
          <ShieldCheck size={18} />
          <div><strong>Governed by design</strong><span>Publisher-only production writes</span></div>
        </div>

        <button className="profile-button" onClick={signOut} title="Sign out">
          <span className="avatar"><CircleUserRound size={20} /></span>
          <span><strong>{identity.email.split("@")[0]}</strong><small>{identity.roles.join(" · ")}</small></span>
          <ChevronDown size={15} />
        </button>
      </aside>

      {menuOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}

      <div className="console-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
          <div className="breadcrumbs"><span>Demo Bank EU</span><b>/</b><strong>{activeItem?.label ?? "Settings"}</strong></div>
          <div className="topbar-actions">
            <label className="global-search"><Search size={16} /><input aria-label="Search" placeholder="Search terms, mappings, traces…" /><kbd>⌘K</kbd></label>
            <button className="icon-button notification" aria-label="Notifications"><Bell size={18} /><span /></button>
            <span className="environment-pill"><i /> Development</span>
          </div>
        </header>
        <main className="workspace">{children}</main>
      </div>
    </div>
  );
}
