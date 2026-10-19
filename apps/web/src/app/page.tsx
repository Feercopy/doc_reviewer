import { redirect } from "next/navigation";

import { appPath } from "@/lib/routing";

export default function HomePage() {
  redirect(appPath(process.env.NEXT_PUBLIC_EXTERNAL_ACCESS_DISABLED === "true" ? "/transition" : "/login"));
}
