export type Role = "user" | "annotator" | "admin";
export type UserStatus = "active" | "blocked";

export type User = {
  id: string;
  login: string;
  display_name: string;
  role: Role;
  status: UserStatus;
};
