import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Atmosphere Agents",
  description: "A standalone, extensible agentic AI platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-50">
          <nav className="bg-white shadow-sm border-b">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex justify-between h-16">
                <div className="flex items-center">
                  <span className="text-2xl mr-2">🤖</span>
                  <span className="font-bold text-xl">Atmosphere Agents</span>
                </div>
                <div className="flex items-center space-x-4">
                  <a href="/" className="text-gray-600 hover:text-gray-900">Dashboard</a>
                  <a href="/agents" className="text-gray-600 hover:text-gray-900">Agents</a>
                  <a href="/logs" className="text-gray-600 hover:text-gray-900">Logs</a>
                  <a href="/activity" className="text-gray-600 hover:text-gray-900">Activity</a>
                  <a href="/approvals" className="text-gray-600 hover:text-gray-900">Approvals</a>
                </div>
              </div>
            </div>
          </nav>
          <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
