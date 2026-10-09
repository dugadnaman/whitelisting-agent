/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/healthz',
        destination: '/api/health',
      },
    ];
  },
};

export default nextConfig;
