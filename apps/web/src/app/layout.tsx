import "./globals.css";

export const metadata = {
  title: "Gate Challenger",
  description: "Gate Challenger Service",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
