"use client";

import { FormEvent, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  deleteProviderKey,
  listProviderKeys,
  saveProviderKey,
  testProviderKey,
  type ProviderKeyRecord,
} from "@/lib/api/provider-settings";
import type { Provider } from "@/lib/api/documents";

const providers: Provider[] = ["openai_compatible", "anthropic_compatible", "hermes"];

export default function SettingsPage() {
  const [keys, setKeys] = useState<ProviderKeyRecord[]>([]);
  const [provider, setProvider] = useState<Provider>("openai_compatible");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("gpt-test");
  const [error, setError] = useState("");
  const [testMessage, setTestMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function refresh() {
    const response = await listProviderKeys();
    setKeys(response.provider_keys);
  }

  useEffect(() => {
    refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load provider keys"));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    setTestMessage("");
    try {
      await saveProviderKey(provider, {
        api_key: apiKey,
        base_url: baseUrl || null,
        default_model: model,
      });
      setApiKey("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save provider key");
    } finally {
      setPending(false);
    }
  }

  async function remove(providerName: Provider) {
    setPending(true);
    setError("");
    setTestMessage("");
    try {
      await deleteProviderKey(providerName);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete provider key");
    } finally {
      setPending(false);
    }
  }

  async function testKey(providerName: Provider) {
    setPending(true);
    setError("");
    setTestMessage("");
    try {
      const result = await testProviderKey(providerName);
      setTestMessage(`${providerName.replaceAll("_", " ")}: ${result.message}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to test provider key");
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell>
      <main className="main stack">
        <div>
          <h1>Settings</h1>
          <p className="muted">Provider keys are encrypted before storage and never shown after save.</p>
        </div>
        <form className="panel stack" onSubmit={submit}>
          <div className="form-grid">
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}>
                {providers.map((item) => (
                  <option key={item} value={item}>
                    {item.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            </label>
            <label>
              API key
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} />
            </label>
            <label>
              Base URL
              <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
            </label>
            <label>
              Default model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
          </div>
          {error ? <div className="error">{error}</div> : null}
          {testMessage ? <div className="success">{testMessage}</div> : null}
          <div>
            <button disabled={pending || !apiKey || !model} type="submit">
              Save key
            </button>
          </div>
        </form>
        <section className="panel">
          {keys.length === 0 ? <div className="muted">No provider keys saved.</div> : null}
          {keys.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Key</th>
                  <th>Base URL</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((item) => (
                  <tr key={item.provider}>
                    <td>{item.provider.replaceAll("_", " ")}</td>
                    <td>{item.default_model}</td>
                    <td>{item.api_key_fingerprint}</td>
                    <td>{item.base_url ?? "-"}</td>
                    <td>
                      <button className="secondary" disabled={pending} type="button" onClick={() => testKey(item.provider)}>
                        Test
                      </button>{" "}
                      <button className="secondary" disabled={pending} type="button" onClick={() => remove(item.provider)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}
