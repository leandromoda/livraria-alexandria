import { ImageResponse } from "next/og";

export const runtime = "edge";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: 32,
          height: 32,
          background: "#4A1628",
          borderRadius: 6,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <span
          style={{
            color: "#C9A84C",
            fontSize: 20,
            fontWeight: 700,
            fontFamily: "serif",
            lineHeight: 1,
          }}
        >
          A
        </span>
      </div>
    ),
    { ...size }
  );
}
