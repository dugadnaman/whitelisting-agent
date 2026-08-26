/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/healthz',
        destination: `${backendUrl}/healthz`,
      },
    ];
  },
};

export default nextConfig;
