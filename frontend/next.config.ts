import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["jacket-oblivion-cyclist.ngrok-free.dev"],
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [{ key: "ngrok-skip-browser-warning", value: "true" }],
      },
    ];
  },
};

export default nextConfig;
