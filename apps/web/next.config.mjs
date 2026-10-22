/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allows a verification build alongside a running `next dev` without clobbering its .next/
  distDir: process.env.NEXT_DIST_DIR || ".next",
};
export default nextConfig;
