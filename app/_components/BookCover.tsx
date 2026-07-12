"use client";

import { useState } from "react";
import Image from "next/image";
import { isOptimizableImage } from "@/lib/images";

interface BookCoverProps {
  src: string | null;
  alt: string;
}

export default function BookCover({ src, alt }: BookCoverProps) {
  const [showFallback, setShowFallback] = useState(!src);

  return (
    <>
      {src && !showFallback && (
        <Image
          src={src}
          alt={alt}
          width={176}
          height={256}
          priority
          unoptimized={!isOptimizableImage(src)}
          className="w-44 h-auto rounded-xl shadow-md border border-[#E6DED3]"
          onError={() => setShowFallback(true)}
        />
      )}
      {(!src || showFallback) && (
        <div className="w-44 h-64 rounded-xl bg-[#4A1628] flex items-center justify-center">
          <span className="text-[#C9A84C] text-5xl font-serif">A</span>
        </div>
      )}
    </>
  );
}
