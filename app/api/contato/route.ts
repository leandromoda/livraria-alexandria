import { Resend } from "resend";
import { NextRequest, NextResponse } from "next/server";

// Rate limiting: 3 envios por IP a cada 5 minutos
const RATE_LIMIT_WINDOW_MS = 5 * 60 * 1000;
const RATE_LIMIT_MAX = 3;
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();

function checkRateLimit(ip: string): boolean {
  const now = Date.now();

  // Limpar entradas expiradas para evitar crescimento ilimitado do Map
  for (const [key, val] of rateLimitMap) {
    if (now > val.resetAt) rateLimitMap.delete(key);
  }

  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return true;
  }
  if (entry.count >= RATE_LIMIT_MAX) return false;
  entry.count += 1;
  return true;
}

const SPAM_PATTERNS = [
  /\b(viagra|cialis|casino|poker|bet\b|apostas|empréstimo rápido)\b/i,
  /\b(ganhe dinheiro|make money|earn \$|renda extra rápida)\b/i,
  /\b(clique aqui|click here|limited offer|oferta limitada)\b/i,
  /\bReclame Aqui\b/i,
  /(https?:\/\/[^\s]{3,}.*){3}/,  // 3+ URLs na mensagem
  /(.)\1{9,}/,                      // 10+ caracteres repetidos
];

function isSpam(text: string): boolean {
  return SPAM_PATTERNS.some((pattern) => pattern.test(text));
}

function buildEmailHtml(params: {
  nome: string;
  email: string;
  assunto: string;
  mensagem: string;
}): string {
  const { nome, email, assunto, mensagem } = params;
  const data = new Date().toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo" });
  // Sanitizar para evitar injeção de HTML no corpo do e-mail
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  return `
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #4A1628; border-bottom: 2px solid #C9A84C; padding-bottom: 8px;">
    Nova mensagem via formulário de contato
  </h2>
  <table style="width: 100%; border-collapse: collapse;">
    <tr>
      <td style="padding: 8px 0; color: #4A4A4A; font-weight: bold; width: 100px;">Nome:</td>
      <td style="padding: 8px 0; color: #0D1B2A;">${esc(nome)}</td>
    </tr>
    <tr>
      <td style="padding: 8px 0; color: #4A4A4A; font-weight: bold;">E-mail:</td>
      <td style="padding: 8px 0; color: #0D1B2A;">${esc(email)}</td>
    </tr>
    <tr>
      <td style="padding: 8px 0; color: #4A4A4A; font-weight: bold;">Assunto:</td>
      <td style="padding: 8px 0; color: #0D1B2A;">${esc(assunto)}</td>
    </tr>
  </table>
  <div style="margin-top: 16px; padding: 16px; background: #F5F0E8; border-radius: 8px;">
    <p style="color: #4A4A4A; font-weight: bold; margin: 0 0 8px;">Mensagem:</p>
    <p style="color: #0D1B2A; white-space: pre-wrap; margin: 0;">${esc(mensagem)}</p>
  </div>
  <p style="margin-top: 16px; font-size: 12px; color: #7B5E3A;">
    Enviado em ${data} via livrariaalexandria.com.br
  </p>
</div>`;
}

export async function POST(request: NextRequest) {
  // Parse do body
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { ok: false, error: "Requisição inválida." },
      { status: 400 }
    );
  }

  const { nome, email, assunto, mensagem, website } = body as Record<string, unknown>;

  // Honeypot: campo oculto preenchido → bot detectado, discard silencioso
  if (typeof website === "string" && website !== "") {
    return NextResponse.json({ ok: true });
  }

  // Rate limiting por IP
  const ip =
    request.headers.get("x-forwarded-for")?.split(",")[0].trim() ?? "unknown";
  if (!checkRateLimit(ip)) {
    return NextResponse.json(
      { ok: false, error: "Muitas tentativas. Aguarde alguns minutos." },
      { status: 429 }
    );
  }

  // Validação de tipos e presença
  if (
    typeof nome !== "string" ||
    typeof email !== "string" ||
    typeof assunto !== "string" ||
    typeof mensagem !== "string"
  ) {
    return NextResponse.json(
      { ok: false, error: "Preencha todos os campos obrigatórios." },
      { status: 400 }
    );
  }

  // Validação de tamanho
  if (nome.trim().length < 2 || nome.trim().length > 80) {
    return NextResponse.json(
      { ok: false, error: "Nome deve ter entre 2 e 80 caracteres." },
      { status: 400 }
    );
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
    return NextResponse.json(
      { ok: false, error: "E-mail inválido." },
      { status: 400 }
    );
  }
  if (assunto.trim().length < 5 || assunto.trim().length > 100) {
    return NextResponse.json(
      { ok: false, error: "Assunto deve ter entre 5 e 100 caracteres." },
      { status: 400 }
    );
  }
  if (mensagem.trim().length < 20 || mensagem.trim().length > 2000) {
    return NextResponse.json(
      { ok: false, error: "Mensagem deve ter entre 20 e 2000 caracteres." },
      { status: 400 }
    );
  }

  // Filtro de spam: discard silencioso
  if (isSpam(`${assunto} ${mensagem}`)) {
    return NextResponse.json({ ok: true });
  }

  // Envio via Resend
  try {
    const resend = new Resend(process.env.RESEND_API_KEY);
    await resend.emails.send({
      from: "Formulário de Contato <noreply@livrariaalexandria.com.br>",
      to: ["contato@livrariaalexandria.com.br"],
      replyTo: email.trim(),
      subject: `[Contato] ${assunto.trim()}`,
      html: buildEmailHtml({
        nome: nome.trim(),
        email: email.trim(),
        assunto: assunto.trim(),
        mensagem: mensagem.trim(),
      }),
    });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Erro ao enviar mensagem. Tente novamente." },
      { status: 500 }
    );
  }

  return NextResponse.json({ ok: true });
}
