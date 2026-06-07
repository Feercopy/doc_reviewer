import { AppShell } from "@/components/AppShell";

export default function DocumentsPage() {
  return (
    <AppShell>
      <main className="main stack">
        <div className="toolbar">
          <div>
            <h1>Documents</h1>
            <p className="muted">History will appear here after upload support lands.</p>
          </div>
        </div>
        <section className="panel muted">No documents yet.</section>
      </main>
    </AppShell>
  );
}
