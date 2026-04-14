"use client";

import { useState } from "react";
import Link from "next/link";

type FormState = "idle" | "loading" | "success" | "error";

const inputClass =
  "w-full px-4 py-2.5 rounded-lg border border-[#E6DED3] bg-white text-[#0D1B2A] placeholder-[#4A4A4A] focus:outline-none focus:border-[#C9A84C] focus:ring-1 focus:ring-[#C9A84C] transition-colors disabled:opacity-50 disabled:cursor-not-allowed";

export default function ContatoForm() {
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [assunto, setAssunto] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [honeypot, setHoneypot] = useState("");
  const [formState, setFormState] = useState<FormState>("idle");
  const [errorMessage, setErrorMessage] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormState("loading");
    setErrorMessage("");

    try {
      const res = await fetch("/api/contato", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome, email, assunto, mensagem, website: honeypot }),
      });

      const data: { ok: boolean; error?: string } = await res.json();

      if (data.ok) {
        setFormState("success");
      } else {
        setFormState("error");
        setErrorMessage(data.error ?? "Erro ao enviar mensagem.");
      }
    } catch {
      setFormState("error");
      setErrorMessage("Erro de conexão. Verifique sua internet e tente novamente.");
    }
  }

  if (formState === "success") {
    return (
      <div className="rounded-xl border border-[#E6DED3] bg-white px-8 py-10 text-center">
        <div className="mb-4 text-4xl">✓</div>
        <h2 className="mb-2 font-serif text-xl font-semibold text-[#0D1B2A]">
          Mensagem enviada!
        </h2>
        <p className="mb-6 text-[#4A4A4A]">
          Recebemos sua mensagem e responderemos em dias úteis.
        </p>
        <Link
          href="/"
          className="inline-block rounded-lg bg-[#4A1628] px-6 py-2.5 font-semibold text-[#F5F0E8] transition-colors hover:bg-[#6B2238]"
        >
          Voltar ao início
        </Link>
      </div>
    );
  }

  const disabled = formState === "loading";

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      {/* Honeypot — invisível para humanos, captura bots */}
      <div
        style={{ position: "absolute", left: "-9999px", opacity: 0 }}
        aria-hidden="true"
      >
        <label htmlFor="website">Website</label>
        <input
          id="website"
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={honeypot}
          onChange={(e) => setHoneypot(e.target.value)}
        />
      </div>

      <div>
        <label
          htmlFor="nome"
          className="mb-1.5 block text-sm font-medium text-[#0D1B2A]"
        >
          Nome <span className="text-[#C9A84C]">*</span>
        </label>
        <input
          id="nome"
          type="text"
          value={nome}
          onChange={(e) => setNome(e.target.value)}
          required
          maxLength={80}
          disabled={disabled}
          placeholder="Seu nome"
          className={inputClass}
        />
      </div>

      <div>
        <label
          htmlFor="email"
          className="mb-1.5 block text-sm font-medium text-[#0D1B2A]"
        >
          E-mail <span className="text-[#C9A84C]">*</span>
        </label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={disabled}
          placeholder="seu@email.com"
          className={inputClass}
        />
      </div>

      <div>
        <label
          htmlFor="assunto"
          className="mb-1.5 block text-sm font-medium text-[#0D1B2A]"
        >
          Assunto <span className="text-[#C9A84C]">*</span>
        </label>
        <input
          id="assunto"
          type="text"
          value={assunto}
          onChange={(e) => setAssunto(e.target.value)}
          required
          maxLength={100}
          disabled={disabled}
          placeholder="Sobre o que você quer falar?"
          className={inputClass}
        />
      </div>

      <div>
        <label
          htmlFor="mensagem"
          className="mb-1.5 block text-sm font-medium text-[#0D1B2A]"
        >
          Mensagem <span className="text-[#C9A84C]">*</span>
        </label>
        <textarea
          id="mensagem"
          value={mensagem}
          onChange={(e) => setMensagem(e.target.value)}
          required
          minLength={20}
          maxLength={2000}
          rows={6}
          disabled={disabled}
          placeholder="Escreva sua mensagem aqui..."
          className={`${inputClass} resize-y`}
        />
        <p className="mt-1 text-right text-xs text-[#4A4A4A]">
          {mensagem.length}/2000
        </p>
      </div>

      {formState === "error" && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {errorMessage}
        </p>
      )}

      <button
        type="submit"
        disabled={disabled}
        className="w-full rounded-lg bg-[#4A1628] px-6 py-3 font-semibold text-[#F5F0E8] transition-colors hover:bg-[#6B2238] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
      >
        {disabled ? "Enviando…" : "Enviar mensagem"}
      </button>
    </form>
  );
}
