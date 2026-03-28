import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";


export const metadata: Metadata = {
  title: "SelçukBolt Web",
  description: "Bolton analizi icin modern web arayuzu.",
  icons: {
    icon: "/favicon.svg",
  },
};


export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="tr">
      <head>
        <style
          dangerouslySetInnerHTML={{
            __html: `
              html, body { margin: 0; padding: 0; min-height: 100%; }
              body {
                font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
                color: #0f172a;
              }
              [data-selcukbolt-shell] {
                min-height: 100vh;
                padding: 24px 20px 40px;
                display: grid;
                gap: 20px;
              }
              [data-selcukbolt-grid] {
                display: grid;
                gap: 20px;
              }
              [data-selcukbolt-card],
              [data-selcukbolt-panel],
              [data-selcukbolt-viewport],
              [data-selcukbolt-toolbar] {
                background: rgba(255, 255, 255, 0.92);
                border: 1px solid rgba(148, 163, 184, 0.22);
                border-radius: 20px;
                box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
              }
              [data-selcukbolt-toolbar] {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                align-items: center;
                justify-content: space-between;
              }
              [data-selcukbolt-panel] { padding: 16px; }
              [data-selcukbolt-viewport] {
                position: relative;
                overflow: hidden;
                min-height: 520px;
              }
              button, input, select, textarea {
                font: inherit;
                border-radius: 14px;
              }
              button {
                border: 1px solid rgba(148, 163, 184, 0.22);
                background: white;
                color: #0f172a;
              }
              input, select, textarea {
                background: rgba(255, 255, 255, 0.96);
                border: 1px solid rgba(148, 163, 184, 0.28);
                color: #0f172a;
                padding: 0.8rem 0.95rem;
              }
            `,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
