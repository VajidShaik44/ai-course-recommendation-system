import os
import sqlite3
import urllib.parse
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq

from database import init_db, get_user_recommendations
from ml_model import recommend_course, stage_aware_recommend

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()

# ---------------- GROQ SETUP ---------------- #
client = None
if os.environ.get("GROQ_API_KEY"):
    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    except:
        client = None


# ---------------- AI FUNCTION ---------------- #
def generate_ai_content(course, skills):
    if client:
        try:
            prompt = f"""
            You are a professional career advisor.

            For the course/career: {course}
            And user skills: {skills}

            Give structured output like:

            WHY:
            - ...
            - ...

            ADVANTAGES:
            - ...
            - ...

            DISADVANTAGES:
            - ...
            - ...

            JOB ROLES:
            - ...
            - ...

            ROADMAP:
            - Step 1 ...
            - Step 2 ...
            """

            response = client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.choices[0].message.content

            return parse_ai_response(text)

        except Exception as e:
            print("Groq error:", e)

    return fallback_content(course, skills)


# ---------------- PARSER ---------------- #
def parse_ai_response(text):
    sections = {
        "why": [],
        "advantages": [],
        "disadvantages": [],
        "jobs": [],
        "roadmap": []
    }

    current = None

    for line in text.split("\n"):
        line = line.strip()

        if "WHY" in line:
            current = "why"
        elif "ADVANTAGES" in line:
            current = "advantages"
        elif "DISADVANTAGES" in line:
            current = "disadvantages"
        elif "JOB ROLES" in line:
            current = "jobs"
        elif "ROADMAP" in line:
            current = "roadmap"
        elif line.startswith("-") and current:
            sections[current].append(line.replace("-", "").strip())

    return sections


# ---------------- FALLBACK ---------------- #
def fallback_content(course, skills):
    return {
        "why": [f"{course} matches your skills: {skills}"],
        "advantages": ["Good demand", "Career growth"],
        "disadvantages": ["Competitive field"],
        "jobs": ["Relevant industry jobs"],
        "roadmap": [
            "Learn basics",
            "Build projects",
            "Gain experience",
            "Apply jobs"
        ]
    }


# ---------------- ROUTES ---------------- #

@app.route("/")
def home():
    return render_template("home.html")


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
            flash("User exists", "error")
        finally:
            conn.close()

    return render_template("register.html")


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

        flash("Invalid login", "error")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")
    return render_template("dashboard.html")


@app.route("/recommend", methods=["POST"])
def recommend():
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
        flash("No results", "warning")
        return redirect("/dashboard")

    results["score"] = (results["score"] * 100).round(2)

    courses = []

    for _, row in results.iterrows():
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


@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")

    data = get_user_recommendations(session["user_id"])
    return render_template("profile.html", recommendations=data)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")