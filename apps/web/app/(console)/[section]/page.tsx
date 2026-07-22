import { notFound } from "next/navigation";
import { SectionContent } from "@/components/section-content";

const sections = new Set(["dashboard", "sources", "model", "proposals", "versions", "playground", "traces", "settings"]);

export default async function SectionPage({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!sections.has(section)) notFound();
  return <SectionContent section={section} />;
}
