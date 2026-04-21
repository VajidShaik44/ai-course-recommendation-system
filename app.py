import os
import sqlite3
import urllib.parse
import json
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

from database import init_db, get_user_recommendations
from ml_model import recommend_course, stage_aware_recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()

# ---------------- GROQ ---------------- #
client = None
if os.environ.get("GROQ_API_KEY"):
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    except:
        client = None

# ---------------- CACHE ---------------- #
ai_cache = {}

# ---------------- AI ENGINE ---------------- #
def generate_ai_content(course, skills):
    cache_key = f"{course}_{skills}"

    if cache_key in ai_cache:
        return ai_cache[cache_key]

    if client:
        try:
            prompt = f"""
Return STRICT JSON only.

Course: {course}
Skills: {skills}

{{
  "why": ["reason"],
  "advantages": ["adv"],
  "disadvantages": ["dis"],
  "jobs": ["job"],
  "roadmap": ["step"]
}}
"""

            response = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.choices[0].message.content.strip()

            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                data = json.loads(text[start:end])
            except:
                return fallback_content(course, skills)

            ai_cache[cache_key] = data
            return data

        except Exception as e:
            print("AI ERROR:", e)

    return fallback_content(course, skills)


# ---------------- FALLBACK ---------------- #
def fallback_content(course, skills):
    return {
        "why": [f"{course} suits your skills"],
        "advantages": [f"{course} has growth"],
        "disadvantages": [f"{course} needs effort"],
        "jobs": [f"{course} jobs"],
        "roadmap": ["Learn basics", "Build projects", "Apply jobs"]
    }


# ---------------- ROUTES ---------------- #

@app.route("/")
def home():
    return render_template("home.html")


# 🔥 FIXED REGISTER
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()

        try:
            hashed = generate_password_hash(password)
            c.execute("INSERT INTO users(username,password) VALUES(?,?)",
                      (username, hashed))
            conn.commit()
            return redirect("/login")
        except:
            flash("User already exists")
        finally:
            conn.close()

    return render_template("register.html")


# 🔥 FIXED LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("students.db")
        c = conn.cursor()
        c.execute("SELECT id, username, password FROM users WHERE username=?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["user"] = user[1]
            session["user_id"] = user[0]
            return redirect("/dashboard")

        flash("Invalid login")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    data = get_user_recommendations(session["user_id"])
    return render_template("dashboard.html", recommendations=data)


# 🔥 FIXED RECOMMEND
@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    if request.method == "GET":
        return redirect("/dashboard")

    if "user" not in session:
        return redirect("/login")

    stage = request.form.get("stage", "")
    skills = request.form.get("skills", "")
    subjects = request.form.get("stream_subjects", "")

    input_text = f"{subjects} {skills}"

    if stage:
        results = stage_aware_recommend(stage, input_text)
    else:
        results = recommend_course(input_text)

    if results is None or results.empty:
        return redirect("/dashboard")

    max_score = results["score"].max()

    if max_score == 0:
        results["score"] = 0
    else:
        results["score"] = ((results["score"] / max_score) * 100).round(2)

    filtered = results[results["score"] > 20]
    if filtered.empty:
        filtered = results.head(3)

    courses = []

    for _, row in filtered.iterrows():
        ai = generate_ai_content(row["course"], skills)

        courses.append({
            "course": row["course"],
            "score": row["score"],
            "why": ai["why"],
            "advantages": ai["advantages"],
            "disadvantages": ai["disadvantages"],
            "jobs": ai["jobs"],
            "roadmap": ai["roadmap"]
        })

    return render_template("result.html", courses=courses, stage=stage)


@app.route("/roadmap/<path:course>")
def roadmap(course):
    course = urllib.parse.unquote(course)

    ai = generate_ai_content(course, "")

    return render_template(
        "roadmap.html",
        course=course,
        steps=ai["roadmap"],
        jobs=ai["jobs"]
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")