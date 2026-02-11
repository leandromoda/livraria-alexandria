import sqlite3
import streamlit as st
import pandas as pd

DB_PATH = "scripts/data/books.db"

# =========================
# DB
# =========================

def get_conn():
    return sqlite3.connect(DB_PATH)


def load_data():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM books", conn)
    conn.close()
    return df


# =========================
# PAGE CONFIG
# =========================

st.set_page_config(
    page_title="Dashboard — Ingest Livros",
    layout="wide"
)

st.title("📚 Dashboard de Progresso — Ingest Pipeline")

# =========================
# LOAD
# =========================

df = load_data()

if df.empty:
    st.warning("Banco local vazio.")
    st.stop()


# =========================
# METRICS
# =========================

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total livros", len(df))
col2.metric("Com sinopse", df['sinopse'].sum())
col3.metric("Com capa", df['capa'].sum())
col4.metric("Publicados", df['publicado'].sum())


# =========================
# PIPELINE STATUS
# =========================

st.subheader("Status por etapa")

status_data = {
    "Etapa": [
        "Prospectado",
        "Slug",
        "Deduplicado",
        "Sinopse",
        "Revisado",
        "Capa",
        "Publicado"
    ],
    "Concluídos": [
        df['prospectado'].sum(),
        df['slugger'].sum(),
        df['dedup'].sum(),
        df['sinopse'].sum(),
        df['revisado'].sum(),
        df['capa'].sum(),
        df['publicado'].sum(),
    ]
}

status_df = pd.DataFrame(status_data)

st.bar_chart(status_df.set_index("Etapa"))


# =========================
# IDIOMA DISTRIBUIÇÃO
# =========================

st.subheader("Distribuição por idioma")

if 'idioma' in df.columns:
    idioma_counts = df['idioma'].value_counts()
    st.bar_chart(idioma_counts)


# =========================
# TABELA DETALHADA
# =========================

st.subheader("Base local")

st.dataframe(
    df[[
        "titulo",
        "autor",
        "isbn",
        "slug",
        "sinopse",
        "revisado",
        "capa",
        "publicado"
    ]],
    use_container_width=True
)


# =========================
# FILTROS
# =========================

st.subheader("Filtrar pendências")

filtro = st.selectbox(
    "Etapa pendente",
    [
        "Sinopse",
        "Revisão",
        "Capa",
        "Publicação"
    ]
)

if filtro == "Sinopse":
    pend = df[df['sinopse'] == 0]

elif filtro == "Revisão":
    pend = df[df['revisado'] == 0]

elif filtro == "Capa":
    pend = df[df['capa'] == 0]

elif filtro == "Publicação":
    pend = df[df['publicado'] == 0]

st.write(f"Pendentes: {len(pend)}")

st.dataframe(
    pend[["titulo", "autor", "slug"]],
    use_container_width=True
)


# =========================
# AUTO REFRESH
# =========================

st.caption("Atualize a página para refletir progresso em tempo real.")
