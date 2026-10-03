import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The UI talks straight to the FastAPI backend (NEXT_PUBLIC_API_URL), so no rewrites
  // are needed and Server-Sent Events aren't buffered by a proxy.
  reactStrictMode: true,
};

export default nextConfig;
