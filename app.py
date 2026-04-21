import os
import sqlite3
import urllib.parse
from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

from database import init_db, get_user_recommendations
from ml_model import recommend_course, stage_aware_recommend

# GPT (SAFE INIT)
client = None
if os.environ.get("OPENAI_API_KEY"):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    except:
        client = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

init_db()


# ---------------- GPT EXPLANATION ---------------- #
def generate_explanation(course, skills):
    if client:
        try:
            prompt = f"""
            Explain why {course} is suitable for someone with skills: {skills}.
            Give short:
            - why
            - advantages
            - disadvantages
            """

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.choices[0].message.content

            return {
                "why": text,
                "advantages": ["High demand", "Growth", "Good salary"],
                "disadvantages": ["Competitive", "Requires learning", "Time investment"]
            }
        except:
            pass

    return {
        "why": f"{course} fits your skills: {skills}",
        "advantages": ["High demand", "Career growth", "Industry relevance"],
        "disadvantages": ["Competitive", "Continuous learning", "Requires effort"]
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
            flash("User already exists", "error")
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
        flash("No results found", "warning")
        return redirect("/dashboard")

    results["score"] = (results["score"] * 100).round(2)

    courses = []
    for _, row in results.iterrows():
        explanation = generate_explanation(row["course"], skills)

        courses.append({
            "course": row["course"],
            "score": row["score"],
            "why": explanation["why"],
            "advantages": explanation["advantages"],
            "disadvantages": explanation["disadvantages"]
        })

    return render_template("result.html", courses=courses, stage=stage)


# ---------------- ROADMAP ---------------- #
def generate_roadmap(course):
    if "Software Engineer" in course:
        return [
            "Learn Python / Java",
            "Master DSA",
            "Learn Web Development",
            "Build Projects",
            "Apply for Jobs"
        ]

    if "Data Scientist" in course:
        return [
            "Learn Python",
            "Study Statistics",
            "Learn ML",
            "Build Projects",
            "Apply for Jobs"
        ]

    return [
        "Learn Basics",
        "Build Skills",
        "Gain Experience",
        "Apply Jobs"
    ]


@app.route("/roadmap/<path:course>")
def roadmap(course):
    course = urllib.parse.unquote(course)
    steps = generate_roadmap(course)
    return render_template("roadmap.html", course=course, steps=steps)


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