import Link from "next/link";

export default function NotFound() {
  return (
    <main className="centered-page">
      <div className="empty-state">
        <span className="eyebrow">404</span>
        <h1>That semantic path does not exist.</h1>
        <p>Return to the workspace and choose a governed route.</p>
        <Link className="button primary" href="/dashboard">Open dashboard</Link>
      </div>
    </main>
  );
}
