import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import ThemeToggle from "./components/ThemeToggle";

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
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var mode = localStorage.getItem('openhoof-theme') || 'system';
                  var dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
                  if (dark) document.documentElement.classList.add('dark');
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body className={inter.className}>
        <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
          <nav className="bg-white dark:bg-gray-900 shadow-sm dark:shadow-gray-900/20 border-b dark:border-gray-800">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
              <div className="flex justify-between h-16">
                <div className="flex items-center">
                  <span className="text-2xl mr-2">🦙</span>
                  <span className="font-bold text-xl dark:text-gray-100">OpenHoof</span>
                </div>
                <div className="flex items-center space-x-4">
                  <a href="/" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Dashboard</a>
                  <a href="/agents" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Agents</a>
                  <a href="/agents/builder" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Agent Builder</a>
                  <a href="/tools" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Tools</a>
                  <a href="/training" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Training</a>
                  <a href="/logs" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Logs</a>
                  <a href="/activity" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Activity</a>
                  <a href="/approvals" className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100">Approvals</a>
                  <ThemeToggle />
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
