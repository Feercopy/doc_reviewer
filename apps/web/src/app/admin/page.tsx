import { redirect } from "next/navigation";

import { appPath } from "@/lib/routing";

export default function AdminPage() {
  redirect(appPath("/admin/users"));
}
