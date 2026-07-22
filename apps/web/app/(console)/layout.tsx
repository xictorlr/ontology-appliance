import { redirect } from "next/navigation";
import { ConsoleFrame } from "@/components/console-frame";
import { getSession } from "@/lib/server-auth";

export default async function ConsoleLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const session = await getSession();
  if (!session) redirect("/login");
  return <ConsoleFrame identity={session}>{children}</ConsoleFrame>;
}
