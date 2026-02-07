/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:18765/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
