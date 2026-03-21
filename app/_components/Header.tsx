"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export default function Header() {
  const pathname = usePathname();
  const router = useRouter();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Fecha menu ao mudar de rota
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = searchRef.current?.value.trim();
    if (q) router.push(`/livros?q=${encodeURIComponent(q)}`);
  }

  const nav = [
    { href: "/listas", label: "Listas" },
    { href: "/livros", label: "Livros" },
    { href: "/autores", label: "Autores" },
    { href: "/categorias", label: "Categorias" },
    { href: "/ofertas", label: "Ofertas" },
  ];

  return (
    <header
      className={`sticky top-0 z-50 bg-[#0D1B2A] text-[#F5F0E8] border-b border-[#1B263B] py-3 transition-shadow ${
        scrolled ? "shadow-lg" : ""
      }`}
    >

      <div className="max-w-6xl mx-auto px-6 flex items-center justify-between gap-4">

        {/* LOGO + NOME */}
        <Link href="/" className="flex items-center gap-3 flex-shrink-0">
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

        {/* NAV — desktop */}
        <nav className="hidden md:flex items-center gap-6 text-sm font-medium">
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

        {/* SEARCH — desktop */}
        <form onSubmit={handleSearch} className="hidden md:block">
          <input
            ref={searchRef}
            type="search"
            placeholder="Buscar livros..."
            className="w-44 px-3 py-1.5 rounded-md bg-[#1B263B] border border-[#415A77] text-sm text-[#F5F0E8] placeholder-[#A8B2C1] focus:outline-none focus:border-[#C9A84C] transition-colors"
          />
        </form>

        {/* HAMBURGER — mobile */}
        <button
          type="button"
          aria-label={menuOpen ? "Fechar menu" : "Abrir menu"}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((v) => !v)}
          className="md:hidden flex flex-col justify-center gap-[5px] w-8 h-8 flex-shrink-0"
        >
          <span
            className={`block h-0.5 bg-[#F5F0E8] transition-all origin-center ${
              menuOpen ? "rotate-45 translate-y-[7px]" : ""
            }`}
          />
          <span
            className={`block h-0.5 bg-[#F5F0E8] transition-all ${
              menuOpen ? "opacity-0 scale-x-0" : ""
            }`}
          />
          <span
            className={`block h-0.5 bg-[#F5F0E8] transition-all origin-center ${
              menuOpen ? "-rotate-45 -translate-y-[7px]" : ""
            }`}
          />
        </button>

      </div>

      {/* MOBILE MENU */}
      {menuOpen && (
        <div className="md:hidden border-t border-[#1B263B] px-6 py-4 space-y-1">

          {/* Busca mobile */}
          <form onSubmit={handleSearch} className="mb-3">
            <input
              type="search"
              placeholder="Buscar livros..."
              className="w-full px-3 py-2 rounded-md bg-[#1B263B] border border-[#415A77] text-sm text-[#F5F0E8] placeholder-[#A8B2C1] focus:outline-none focus:border-[#C9A84C] transition-colors"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  const q = (e.target as HTMLInputElement).value.trim();
                  if (q) router.push(`/livros?q=${encodeURIComponent(q)}`);
                }
              }}
            />
          </form>

          {nav.map((item) => {
            const active = pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block py-2 text-sm font-medium transition-colors ${
                  active
                    ? "text-[#C9A84C]"
                    : "text-[#F5F0E8] hover:text-[#C9A84C]"
                }`}
              >
                {item.label}
              </Link>
            );
          })}

        </div>
      )}

    </header>
  );
}
