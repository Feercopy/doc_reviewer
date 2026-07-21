export type Role = "user" | "annotator" | "admin";
export type UserStatus = "active" | "blocked" | "deleted";

export type User = {
  id: string;
  login: string;
  display_name: string;
  role: Role;
  status: UserStatus;
};
