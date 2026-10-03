import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "CI help · GoodFirst",
  description: "Paste a pull request whose checks failed. A local model explains the failure from the real log.",
};

export default function CILayout({ children }: { children: React.ReactNode }) {
  return children;
}
