"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export default function Header() {

  const pathname = usePathname();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {

    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };

    window.addEventListener("scroll", handleScroll);

    return () => window.removeEventListener("scroll", handleScroll);

  }, []);

  const nav = [
    { href: "/listas", label: "Listas" },
    { href: "/livros", label: "Livros" },
    { href: "/autores", label: "Autores" },
    { href: "/categorias", label: "Categorias" },
    { href: "/ofertas", label: "Ofertas" },
  ];

  return (
    <header
      className={`sticky top-0 z-50 bg-[#0D1B2A] text-[#F5F0E8] border-b border-[#1B263B] transition-all ${
        scrolled ? "py-2 shadow-lg" : "py-3"
      }`}
    >

      <div className="max-w-6xl mx-auto px-6 flex items-center justify-between">

        {/* LOGO + NOME */}
        <Link href="/" className="flex items-center gap-3">

          <Image
            src="/logo_livraria_alexandria.png"
            alt="Livraria Alexandria"
            width={44}
            height={44}
            priority
          />

          <span className="font-serif text-lg tracking-wide">
            Livraria Alexandria
          </span>

        </Link>

        {/* NAV */}
        <nav className="flex items-center gap-6 text-sm font-medium">

          {nav.map((item) => {

            const active = pathname.startsWith(item.href);

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative transition-colors ${
                  active ? "text-[#C9A84C]" : "hover:text-[#C9A84C]"
                }`}
              >

                {item.label}

                {active && (
                  <span className="absolute left-0 -bottom-1 w-full h-[2px] bg-[#C9A84C]" />
                )}

              </Link>
            );
          })}

        </nav>

        {/* SEARCH */}
        <input
          type="search"
          placeholder="Buscar..."
          className="hidden md:block w-40 px-3 py-1.5 rounded-md bg-[#1B263B] border border-[#415A77] text-sm text-[#F5F0E8] placeholder-[#A8B2C1] focus:outline-none focus:border-[#C9A84C]"
        />

      </div>

    </header>
  );
}
