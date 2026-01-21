# app.py
import time
import random
import csv
import os
from dataclasses import dataclass
import streamlit as st

SCORES_FILE = "scores.csv"
NUM_QUESTIONS = 10

MAX_ABS_ANSWER = 143          # answers must be under 144 in magnitude
MAX_DIV_ANSWER = 12           # division highest answer (quotient)

st.set_page_config(page_title="Speed Math", page_icon="🔥", layout="centered")

@dataclass
class Question:
    text: str
    answer: int

def clamp_ok(ans: int) -> bool:
    return abs(ans) <= MAX_ABS_ANSWER

def make_question(rng: random.Random) -> Question:
    """
    Generates +, -, ×, ÷ questions with constraints:
    - abs(answer) <= 143
    - division answer <= 12
    """
    op = rng.choice(["+", "-", "×", "÷"])

    if op == "÷":
        # quotient <= 12, keep operands reasonable, ensure integer division
        q = rng.randint(0, MAX_DIV_ANSWER)
        b = rng.randint(1, 12)   # divisor
        a = b * q
        # a can be 0..144, but q<=12 and b<=12 => a<=144; if 144 happens, q=12,b=12 => a=144; answer still 12 ok
        # answer constraint is about answer, not operands. If you also want operands <144, it's still fine.
        return Question(f"{a} ÷ {b}", q)

    if op == "×":
        # ensure product within abs <= 143
        # choose a and b from small ranges then validate
        while True:
            a = rng.randint(-12, 12)
            b = rng.randint(-12, 12)
            ans = a * b
            if clamp_ok(ans):
                return Question(f"{a} × {b}", ans)

    if op == "+":
        while True:
            a = rng.randint(1, 12)
            b = rng.randint(1, 12)
            ans = a + b
            if clamp_ok(ans):
                return Question(f"{a} + {b}", ans)

    # op == "-"
    while True:
        a = rng.randint(1, 24)
        b = rng.randint(1, 24)
        ans = a - b
        if clamp_ok(ans):
            return Question(f"{a} - {b}", ans)

def load_scores() -> list[float]:
    if not os.path.exists(SCORES_FILE):
        return []
    out = []
    with open(SCORES_FILE, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append(float(row["score"]))
            except Exception:
                pass
    return out

def save_score(score: float, accuracy: float, time_taken: float):
    file_exists = os.path.exists(SCORES_FILE)
    with open(SCORES_FILE, "a", newline="") as f:
        fieldnames = ["timestamp", "score", "accuracy", "time_taken"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": int(time.time()),
                "score": score,
                "accuracy": accuracy,
                "time_taken": time_taken,
            }
        )

def percentile_rank(user_score: float, history: list[float]) -> float | None:
    """
    Higher percentile = better.
    Lower score is better, so percentile counts how many past scores are WORSE (greater).
    """
    if not history:
        return None
    worse = sum(1 for s in history if s > user_score)
    return 100.0 * worse / len(history)

def reset_all():
    keys = [
        "started", "finished", "start_time", "questions", "idx",
        "user_answers", "last_input", "seed"
    ]
    for k in keys:
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

    history = load_scores()
    save_score(score, accuracy, time_taken)
    pct = percentile_rank(score, history)  # compare vs history BEFORE this run

    st.session_state.finished = True
    st.session_state.time_taken = time_taken
    st.session_state.correct = correct
    st.session_state.accuracy = accuracy
    st.session_state.score = score
    st.session_state.percentile = pct
    st.session_state.show_answers = show_answers

    st.rerun()

st.title("🔥 Speed Math (Enter-to-Next)")
st.caption("Score = (1/accuracy) × time_taken_seconds  •  lower is better 🙏")

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
    st.write("Press **Start**. Then spam until finished :)")

    if st.button("🚀 Start", type="primary", use_container_width=True):
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
    # finished screen
    if st.session_state.finished:
        st.success("Done")

        time_taken = st.session_state.time_taken
        correct = st.session_state.correct
        accuracy = st.session_state.accuracy
        score = st.session_state.score
        pct = st.session_state.percentile

        st.write(f"**Time taken:** {time_taken:.3f} s")
        st.write(f"**Accuracy:** {correct}/{NUM_QUESTIONS} = {accuracy*100:.1f}%")
        st.write(f"**Final score:** {score:.4f}" if score != float("inf") else "**Final score:** ∞ (accuracy was 0 💀)")

        if pct is None:
            st.write("**Percentile:** N/A (no history yet on this device)")
        else:
            st.write(f"**Percentile:** {pct:.1f}th (higher = better)")

        if st.session_state.get("show_answers", True):
            st.divider()
            st.subheader("Review")
            for i, q in enumerate(st.session_state.questions, start=1):
                ua = st.session_state.user_answers[i-1]
                ok = (ua == q.answer)
                st.write(
                    f"Q{i}. {q.text} = **{q.answer}**  |  you: **{ua if ua is not None else '—'}**  "
                    f"{'✅' if ok else '❌'}"
                )

        st.divider()
        st.caption("History is stored in scores.csv on this machine. Delete it to reset percentile baselines.")
        if st.button("🔁 New run", use_container_width=True):
            reset_all()

    else:
        # in-progress
        questions: list[Question] = st.session_state.questions
        idx: int = st.session_state.idx

        st.info("Timer is running… Enter submits and jumps to the next one")

        # Progress
        st.progress(idx / NUM_QUESTIONS)
        st.write(f"**Question {idx+1}/{NUM_QUESTIONS}**")

        q = questions[idx]
        st.markdown(f"### {q.text} = ?")

        # Form so Enter triggers submit
        with st.form("single_q_form", clear_on_submit=True):
            raw = st.text_input("Type answer and press Enter", value="", placeholder="e.g. 42")
            submitted = st.form_submit_button("Next (Enter)")

        colA, colB, colC = st.columns([1, 1, 1])
        with colA:
            if st.button("⏭ Skip", use_container_width=True):
                st.session_state.user_answers[idx] = None
                st.session_state.idx += 1
                if st.session_state.idx >= NUM_QUESTIONS:
                    finish_quiz(show_answers)
                st.rerun()
        with colB:
            if st.button("Finish Quiz", type="primary", use_container_width=True):
                # Finish immediately, even if you haven't answered all
                finish_quiz(show_answers)
        with colC:
            if st.button("Reset", use_container_width=True):
                reset_all()

        if submitted:
            # store answer (or None if invalid)
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
