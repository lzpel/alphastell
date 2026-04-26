import type { Metadata } from "next";
import { CSSProperties } from "react";

export const metadata: Metadata = {
  title: "alphastell",
  description: "A stellarator design tool written in Rust",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const full: CSSProperties = {
    width: '100%',
    height: '100%',
  }
  return (
    <html lang="en" style={full}>
      <body style={full}>{children}</body>
    </html>
  );
}
