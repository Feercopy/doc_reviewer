import { apiFetch } from "./client";
import type { User } from "./types";

export type LoginResponse = {
  user: User;
};

export async function login(loginName: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ login: loginName, password }),
  });
}

export async function logout(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/auth/logout", { method: "POST" });
}

export async function me(): Promise<User> {
  return apiFetch<User>("/auth/me");
}
