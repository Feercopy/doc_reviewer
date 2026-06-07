import { apiFetch } from "./client";
import type { Role, User, UserStatus } from "./types";

export type UsersListResponse = {
  users: User[];
};

export type CreateUserPayload = {
  login: string;
  display_name: string;
  password: string;
  role: Role;
  status: UserStatus;
};

export type PatchUserPayload = {
  display_name?: string;
  role?: Role;
  status?: UserStatus;
};

export async function listUsers(): Promise<UsersListResponse> {
  return apiFetch<UsersListResponse>("/admin/users");
}

export async function createUser(payload: CreateUserPayload): Promise<User> {
  return apiFetch<User>("/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function patchUser(userId: string, payload: PatchUserPayload): Promise<User> {
  return apiFetch<User>(`/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function resetPassword(userId: string, password: string): Promise<User> {
  return apiFetch<User>(`/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}
