/** @type {import('next').NextConfig} */

// Comma-separated extra hosts when using ngrok / tunnel in dev (no scheme).
// Example: ALLOWED_DEV_ORIGINS=abc123.ngrok-free.app,other.ngrok-free.app
const extraOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

const nextConfig = {
  allowedDevOrigins: [
    "63f7-50-7-253-202.ngrok-free.app",
    ...extraOrigins,
  ],
};

module.exports = nextConfig;
