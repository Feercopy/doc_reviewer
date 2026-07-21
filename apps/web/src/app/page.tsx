import { redirect } from "next/navigation";

import { appPath } from "@/lib/routing";

export default function HomePage() {
  redirect(appPath("/login"));
}
