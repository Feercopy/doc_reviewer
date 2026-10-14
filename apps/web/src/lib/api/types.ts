export type Role = "user" | "superuser" | "annotator" | "admin";
export type UserStatus = "active" | "blocked" | "deleted";

export type User = {
  id: string;
  login: string;
  display_name: string;
  role: Role;
  status: UserStatus;
};
