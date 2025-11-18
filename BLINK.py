# blink_streamlit_app.py
# B.L.I.N.K - Streamlit app (single-file)
# Features: habit creation, logging, analytics, beautiful UI (CSS + SVG), local SQLite storage

import streamlit as st
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import io
import base64
import random

# --- Page config ---
st.set_page_config(page_title="B.L.I.N.K — Behavior Log", layout="wide", initial_sidebar_state="expanded")

# --- CSS / styles ---
PAGE_CSS = r"""
<style>
:root{
  --bg:#0f1724; /* deep */
  --card:#0b1220; /* card */
  --muted:#9aa5b1;
  --accent1: linear-gradient(90deg,#7c3aed,#06b6d4);
}

body {
  background: radial-gradient(circle at 10% 10%, rgba(124,58,237,0.08), transparent 10%),
              radial-gradient(circle at 90% 90%, rgba(6,182,212,0.06), transparent 10%),
              #071028;
  color:#e6eef6;
}

.header {
  display:flex;align-items:center;gap:18px;padding:18px;border-radius:14px;
  background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
  box-shadow: 0 6px 18px rgba(2,6,23,0.6);
}
.h-title{font-size:22px;font-weight:700;margin:0}
.h-sub{color:var(--muted);margin:0;font-size:13px}
.card{background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));padding:14px;border-radius:12px}
.kpi{display:flex;gap:14px}
.kpi .k{padding:12px;border-radius:10px;background:rgba(255,255,255,0.02);min-width:120px}
.small{color:var(--muted);font-size:12px}
.btn-primary{background:transparent;border:1px solid rgba(255,255,255,0.06);padding:8px;border-radius:8px}
.progress-wrap{background:rgba(255,255,255,0.03);padding:8px;border-radius:10px}
.footer{color:var(--muted);font-size:12px;margin-top:10px}

/* subtle confetti animation */
@keyframes fall {0%{transform:translateY(-10vh) rotate(0);}100%{transform:translateY(110vh) rotate(360deg);}}
.confetti{position:fixed;left:0;top:0;width:100%;height:0;pointer-events:none;}
.confetti span{position:absolute;top:-10vh;font-size:12px;opacity:0.9;animation:fall linear infinite}

</style>
"""

# small hero SVG
HERO_SVG = r'''<svg width="72" height="72" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect width="72" height="72" rx="16" fill="url(#g)"/>
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c3aed"/><stop offset="1" stop-color="#06b6d4"/></linearGradient></defs>
<g opacity="0.98"><path d="M36 18C29 18 24 23 24 30C24 40 36 54 36 54C36 54 48 40 48 30C48 23 43 18 36 18Z" fill="white" opacity="0.95"/></g>
</svg>'''

# --- Database ---
DB_PATH = "blink_data.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            target INTEGER DEFAULT 1,
            color TEXT DEFAULT '#7c3aed',
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER,
            ts TEXT,
            note TEXT,
            FOREIGN KEY(habit_id) REFERENCES habits(id)
        )
        """
    )
    conn.commit()
    return conn

conn = init_db()

# --- Helpers ---

def add_habit(name, category, target, color):
    cur = conn.cursor()
    cur.execute("INSERT INTO habits (name, category, target, color, created_at) VALUES (?,?,?,?,?)",
                (name, category, int(target), color, datetime.utcnow().isoformat()))
    conn.commit()

def get_habits():
    return pd.read_sql_query("SELECT * FROM habits ORDER BY id DESC", conn)

def add_log(habit_id, ts=None, note=None):
    if ts is None:
        ts = datetime.utcnow().isoformat()
    cur = conn.cursor()
    cur.execute("INSERT INTO logs (habit_id, ts, note) VALUES (?,?,?)", (habit_id, ts, note))
    conn.commit()

def get_logs():
    return pd.read_sql_query("SELECT l.id, l.habit_id, l.ts, l.note, h.name as habit_name FROM logs l LEFT JOIN habits h ON h.id=l.habit_id ORDER BY ts DESC", conn)

# Analytics

def weekly_counts(df_logs, days=28):
    if df_logs.empty:
        return pd.Series(dtype=int)
    df = df_logs.copy()
    df['ts'] = pd.to_datetime(df['ts'])
    start = pd.Timestamp.utcnow() - pd.Timedelta(days=days)
    rng = pd.date_range(start=start.normalize(), periods=days+1, freq='D')
    idx = rng
    s = df.set_index('ts').groupby(pd.Grouper(freq='D')).size().reindex(idx, fill_value=0)
    s.index = s.index.normalize()
    return s

def calc_streaks(df_logs, habit_id=None):
    if df_logs.empty:
        return 0,0
    df = df_logs.copy()
    df['ts'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
    if habit_id:
        df = df[df['habit_id']==habit_id]
    days = sorted(set([d.date() for d in df['ts']]))
    if not days: return 0,0
    streak=0; best=0; prev=None
    for d in days:
        if prev is None or d == prev + timedelta(days=1):
            streak += 1
        else:
            streak = 1
        prev = d
        best = max(best, streak)
    # current streak: count from last day backwards until gap
    today = datetime.utcnow().date()
    cur_streak = 0
    dset = set(days)
    d = max(days)
    while d in dset:
        cur_streak += 1
        d = d - timedelta(days=1)
    return cur_streak, best

# --- UI ---

st.markdown(PAGE_CSS, unsafe_allow_html=True)

# confetti markup (small)
confetti_html = '<div class="confetti">' + ''.join([f'<span style="left:{random.randint(0,100)}%;animation-duration:{random.uniform(4,9):.1f}s;transform:rotate({random.randint(0,360)}deg);">🎉</span>' for _ in range(8)]) + '</div>'
st.markdown(confetti_html, unsafe_allow_html=True)

with st.container():
    cols = st.columns([1,6,1])
    with cols[1]:
        st.markdown('<div class="header">' + HERO_SVG + '<div><p class="h-title">B.L.I.N.K — Behavior Log</p><p class="h-sub">Acompanhe hábitos, registre vitórias e mantenha o ritmo.</p></div></div>', unsafe_allow_html=True)

# Sidebar controls
with st.sidebar:
    st.header("Controles")
    if st.button("Exportar CSV"):
        df_logs = get_logs()
        csv = df_logs.to_csv(index=False).encode('utf-8')
        b64 = base64.b64encode(csv).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="blink_logs.csv">Baixar logs</a>'
        st.markdown(href, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Configurações**")
    tz = st.selectbox("Fuso horário (exibição)",["UTC","Local (sistema)"])
    st.markdown("---")
    st.markdown("**Inspiração**")
    if st.button("Gerar citação motivacional"):
        quotes = [
            "Progresso pequeno, vitória grande.",
            "Consistência vence velocidade.",
            "Faça hoje o que seu futuro eu agradecerá.",
            "Uma ação por vez. Repita." 
        ]
        st.success(random.choice(quotes))

# Main layout: two columns
col_left, col_right = st.columns([2,3])

with col_left:
    st.subheader("Registrar / Gerenciar")
    with st.expander("Criar novo hábito"):
        with st.form("form_habit", clear_on_submit=True):
            name = st.text_input("Nome do hábito", placeholder="Ex: Exercício, Meditação")
            category = st.text_input("Categoria (opcional)")
            target = st.number_input("Meta por dia", min_value=1, max_value=20, value=1)
            color = st.color_picker("Cor do cartão", value="#7c3aed")
            submitted = st.form_submit_button("Criar hábito")
            if submitted:
                if not name.strip():
                    st.error("Nome obrigatório")
                else:
                    add_habit(name.strip(), category.strip(), int(target), color)
                    st.success("Hábito criado")

    st.markdown("---")
    st.subheader("Registrar atividade")
    df_h = get_habits()
    if df_h.empty:
        st.info("Nenhum hábito criado. Crie um no painel acima.")
    else:
        with st.form("log_form"):
            h_opt = {row['name']: row['id'] for _, row in df_h.iterrows()}
            habit_sel = st.selectbox("Escolha hábito", options=list(h_opt.keys()))
            note = st.text_input("Observação (opcional)")
            if st.form_submit_button("Registrar agora"):
                add_log(h_opt[habit_sel], datetime.utcnow().isoformat(), note)
                st.success("Registrado ✅")

    st.markdown("---")
    st.subheader("Lista de hábitos")
    for _, r in df_h.iterrows():
        with st.container():
            c1, c2 = st.columns([6,1])
            c1.markdown(f"**{r['name']}**  <span class=\"small\">{r['category'] or ''}</span>", unsafe_allow_html=True)
            if c2.button("+1", key=f"quick_{r['id']}"):
                add_log(r['id'])
                st.experimental_rerun()

with col_right:
    st.subheader("Painel — Resumo")
    df_logs = get_logs()
    df_h = get_habits()

    total_actions = len(df_logs)
    unique_habits = len(df_h)
    cur_streak, best_streak = calc_streaks(df_logs)

    kcol1, kcol2, kcol3 = st.columns(3)
    kcol1.metric("Ações totais", total_actions)
    kcol2.metric("Hábitos ativos", unique_habits)
    kcol3.metric("Sequência atual", cur_streak)

    st.markdown("---")
    st.markdown("**Atividade últimos 28 dias**")
    s = weekly_counts(df_logs, days=28)
    fig, ax = plt.subplots(figsize=(8,2.2))
    ax.bar(s.index, s.values)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    st.pyplot(fig)

    st.markdown("---")
    st.subheader("Detalhes dos logs")
    if df_logs.empty:
        st.info("Sem registros ainda")
    else:
        st.dataframe(df_logs[['ts','habit_name','note']].assign(ts=lambda d: pd.to_datetime(d['ts']).dt.tz_localize(None)))

# bottom: calendar heatmap (simple)
st.markdown("---")
st.subheader("Mapa de calor: últimos 30 dias")

s30 = weekly_counts(df_logs, days=30)
if s30.empty:
    st.info("Sem dados suficientes")
else:
    fig2, ax2 = plt.subplots(figsize=(10,2.6))
    dates = s30.index
    vals = s30.values
    # Normalize for color intensity
    norm = (vals - vals.min()) / (vals.max() - vals.min() + 1e-6)
    for i, d in enumerate(dates):
        ax2.add_patch(plt.Rectangle((i,0),1,1, color=(0.2,0.6,0.9,norm[i]*0.9+0.06)))
    ax2.set_xlim(0,len(dates))
    ax2.set_ylim(0,1)
    ax2.set_yticks([])
    ax2.set_xticks(range(len(dates)))
    ax2.set_xticklabels([d.strftime('%d %b') for d in dates], rotation=45, ha='right')
    plt.tight_layout()
    st.pyplot(fig2)

st.markdown("---")
with st.container():
    st.markdown('<div class="card"><strong>Dicas rápidas</strong><ul><li>Defina metas pequenas e claras.</li><li>Use a função +1 para manter a rotina.</li><li>Revise progresso semanalmente.</li></ul></div>', unsafe_allow_html=True)
    st.markdown('<p class="footer">Feito para ser simples, resistente e direto. Salve o arquivo e execute: <code>streamlit run blink_streamlit_app.py</code></p>', unsafe_allow_html=True)

# End of file
