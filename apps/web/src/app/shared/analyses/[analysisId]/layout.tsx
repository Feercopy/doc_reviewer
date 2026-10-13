import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Результаты анализа - Gate Challenger",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function SharedAnalysisLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
