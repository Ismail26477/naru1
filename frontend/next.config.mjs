/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // Re-export REACT_APP_BACKEND_URL (platform protected var) as NEXT_PUBLIC_
    NEXT_PUBLIC_BACKEND_URL: process.env.REACT_APP_BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || '',
  },
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'images.unsplash.com' },
      { protocol: 'https', hostname: 'images.pexels.com' },
    ],
  },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
