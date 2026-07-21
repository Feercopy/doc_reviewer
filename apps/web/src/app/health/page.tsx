"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL } from "@/lib/api/client";

type HealthState = "checking" | "ok" | "failed";

export default function HealthPage() {
  const [state, setState] = useState<HealthState>("checking");
  const [detail, setDetail] = useState("");

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(response.statusText);
        }
        const payload = (await response.json()) as { status?: string };
        if (payload.status !== "ok") {
          throw new Error("Unexpected health response");
        }
        setState("ok");
        setDetail("API online");
      })
      .catch((error) => {
        setState("failed");
        setDetail(error instanceof Error ? error.message : "API unavailable");
      });
  }, []);

  return (
    <main className="main stack">
      <h1>Health</h1>
      <section className="panel">
        <strong>{state}</strong>
        <p className={state === "failed" ? "error" : "muted"}>{detail || "Checking API"}</p>
      </section>
    </main>
  );
}
