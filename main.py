# main.py
# Streamlit Speed Math: 10 random questions (+, -, ×, ÷)
# - Enter advances to next question (one-at-a-time form)
# - Answers constrained: |answer| <= 143, division quotient <= 12
# - Global/communal percentile via a shared SQLite DB file (global_scores.db)
#   (Shared across all users on the same deployed server)

import time
import random
import sqlite3
from pathlib import Path
from dataclasses import dataclass

import streamlit as st

# ----------------- Config -----------------
NUM_QUESTIONS = 10
MAX_ABS_ANSWER = 143          # all answers under 144 in magnitude
MAX_DIV_ANSWER = 12           # division highest answer (quotient)
DB_PATH = Path("global_scores.db")

st.set_page_config(page_title="Speed Math Global", page_icon=" ", layout="centered")


# ----------------- Data models -----------------
@dataclass
class Question:
    text: str
    answer: int


# ----------------- Question generation -----------------
def clamp_ok(ans: int) -> bool:
    return abs(ans) <= MAX_ABS_ANSWER


def make_question(rng: random.Random) -> Question:
    """
    Generates +, -, ×, ÷ questions with constraints:
    - abs(answer) <= 143
    - division quotient <= 12
    """
    op = rng.choice(["+", "-", "×", "÷"])

    if op == "÷":
        # Ensure integer division, quotient <= 12
        q = rng.randint(0, MAX_DIV_ANSWER)
        b = rng.randint(1, 12)
        a = b * q
        return Question(f"{a} ÷ {b}", q)

    if op == "×":
        # Keep products within |answer| <= 143
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a * b
            if clamp_ok(ans):
                return Question(f"{a} × {b}", ans)

    if op == "+":
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a + b
            if clamp_ok(ans):
                return Question(f"{a} + {b}", ans)

    # op == "-"
    while True:
        a = rng.randint(-12, 12)
        b = rng.randint(-12, 12)
        ans = a - b
        if clamp_ok(ans):
            return Question(f"{a} - {b}", ans)


# ----------------- Global communal DB (SQLite file) -----------------
def _get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            score REAL NOT NULL,
            accuracy REAL NOT NULL,
            time_taken REAL NOT NULL
        );
        """
    )
    conn.commit()
    return conn


@st.cache_resource
def db_conn() -> sqlite3.Connection:
    # One shared connection per server process
    return _get_db_connection()


def insert_score(score: float, accuracy: float, time_taken: float) -> None:
    conn = db_conn()
    conn.execute(
        "INSERT INTO scores (ts, score, accuracy, time_taken) VALUES (?, ?, ?, ?)",
        (int(time.time()), float(score), float(accuracy), float(time_taken)),
    )
    conn.commit()


def get_global_scores() -> list[float]:
    conn = db_conn()
    rows = conn.execute("SELECT score FROM scores").fetchall()
    return [float(r[0]) for r in rows]


def percentile_rank(user_score: float, history: list[float]) -> float | None:
    """
    Higher percentile = better.
    Lower score is better, so percentile counts how many past scores are worse (greater).
    """
    if not history:
        return None
    worse = sum(1 for s in history if s > user_score)
    return 100.0 * worse / len(history)


# ----------------- Session helpers -----------------
def reset_all():
    for k in [
        "started",
        "finished",
        "start_time",
        "questions",
        "idx",
        "user_answers",
        "seed",
        "last_run",
    ]:
        st.session_state.pop(k, None)
    st.rerun()


def finish_quiz(show_answers: bool):
    end_time = time.perf_counter()
    time_taken = end_time - st.session_state.start_time

    questions: list[Question] = st.session_state.questions
    user_answers: list[int | None] = st.session_state.user_answers

    correct = 0
    for q, ua in zip(questions, user_answers):
        if ua is not None and ua == q.answer:
            correct += 1

    accuracy = correct / len(questions)
    score = float("inf") if accuracy == 0 else (1.0 / accuracy) * time_taken

    # Percentile vs GLOBAL history before inserting this run
    history = get_global_scores()
    pct = None if score == float("inf") else percentile_rank(score, history)

    # Save run to global DB (skip inf to avoid poisoning stats)
    if score != float("inf"):
        insert_score(score, accuracy, time_taken)

    st.session_state.finished = True
    st.session_state.last_run = {
        "time_taken": time_taken,
        "correct": correct,
        "accuracy": accuracy,
        "score": score,
        "percentile": pct,
        "show_answers": show_answers,
    }
    st.rerun()


# ----------------- UI -----------------
st.title("Global Speed Math")
st.caption("Score = (1/accuracy) × time_taken_seconds  •  lower is better   •  Percentile is vs everyone")

col1, col2 = st.columns(2)
with col1:
    seed = st.number_input("Random seed (optional)", value=0, step=1)
with col2:
    show_answers = st.checkbox("Show correct answers at end", value=True)

st.divider()

if "started" not in st.session_state:
    st.session_state.started = False
if "finished" not in st.session_state:
    st.session_state.finished = False

if not st.session_state.started:
    st.write("Press **Start**. Then continue until finished (10 questions)")

    if st.button("Start", type="primary", use_container_width=True):
        rng = random.Random(int(seed) if seed != 0 else None)
        st.session_state.seed = seed
        st.session_state.questions = [make_question(rng) for _ in range(NUM_QUESTIONS)]
        st.session_state.user_answers = [None] * NUM_QUESTIONS
        st.session_state.idx = 0
        st.session_state.start_time = time.perf_counter()
        st.session_state.started = True
        st.session_state.finished = False
        st.rerun()

else:
    # Finished screen
    if st.session_state.finished:
        r = st.session_state.last_run
        st.success("Done")

        st.write(f"**Time taken:** {r['time_taken']:.3f} s")
        st.write(f"**Accuracy:** {r['correct']}/{NUM_QUESTIONS} = {r['accuracy']*100:.1f}%")
        st.write(f"**Final score:** {r['score']:.4f}" if r["score"] != float("inf") else "**Final score:** ∞ (accuracy was 0)")

        if r["percentile"] is None:
            st.write("**Percentile:** N/A (not enough global data yet, or score was ∞)")
        else:
            st.write(f"**Percentile:** {r['percentile']:.1f}th (higher = better)")

        global_scores = get_global_scores()
        st.caption(f"Global attempts recorded: **{len(global_scores)}**")

        if r.get("show_answers", True):
            st.divider()
            st.subheader("Review")
            for i, q in enumerate(st.session_state.questions, start=1):
                ua = st.session_state.user_answers[i - 1]
                ok = (ua == q.answer)
                st.write(
                    f"Q{i}. {q.text} = **{q.answer}**  |  you: **{ua if ua is not None else '—'}**  "
                    f"{'✅' if ok else '❌'}"
                )

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            if st.button("New run", use_container_width=True):
                reset_all()
        with c2:
            if st.button("Reset (local session only)", use_container_width=True):
                reset_all()

    # In-progress screen
    else:
        idx = st.session_state.idx
        questions: list[Question] = st.session_state.questions
        q = questions[idx]

        st.info("Timer is running… Enter submits and jumps to the next one")
        st.progress(idx / NUM_QUESTIONS)
        st.write(f"**Question {idx+1}/{NUM_QUESTIONS}**")
        st.markdown(f"### {q.text} = ?")

        # Form makes Enter submit
        with st.form("single_q_form", clear_on_submit=True):
            raw = st.text_input("Type answer and press Enter", value="", placeholder="e.g. 42")
            submitted = st.form_submit_button("Next (Enter)")

        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("⏭ Skip", use_container_width=True):
                st.session_state.user_answers[idx] = None
                st.session_state.idx += 1
                if st.session_state.idx >= NUM_QUESTIONS:
                    finish_quiz(show_answers)
                st.rerun()

        with c2:
            if st.button("Finish Quiz", type="primary", use_container_width=True):
                finish_quiz(show_answers)

        with c3:
            if st.button("Reset", use_container_width=True):
                reset_all()

        if submitted:
            raw = raw.strip()
            try:
                val = int(raw)
            except Exception:
                val = None

            st.session_state.user_answers[idx] = val
            st.session_state.idx += 1

            if st.session_state.idx >= NUM_QUESTIONS:
                finish_quiz(show_answers)
            else:
                st.rerun()
