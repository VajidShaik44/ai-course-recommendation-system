from flask import Flask, render_template, request, redirect, session, flash
from database import init_db, get_all_courses, add_course, delete_course, get_all_users, get_all_recommendations, get_stats
from ml_model import recommend_course, stage_aware_recommend

import sqlite3

app = Flask(__name__)
app.secret_key = "secret123"

init_db()

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
            c.execute("INSERT INTO users(username,password) VALUES(?,?)",
                      (username,password))
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect("/login")
        except:
            flash("Username already exists!", "error")
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
        c.execute("SELECT id, username, password, COALESCE(is_admin, 0) FROM users WHERE username=? AND password=?",
                  (username,password))
        user = c.fetchone()
        conn.close()

        if user:
            session["user"] = user[1]
            session["user_id"] = user[0]
            session["is_admin"] = user[3]
            if user[3] == 1:
                return redirect("/admin")
            return redirect("/dashboard")
        else:
            flash("Invalid username or password!", "error")

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
    stream_subjects = request.form.get("stream_subjects", "")
    skills = request.form.get("skills", "")
    
    # Combine inputs
    input_text = f"{stream_subjects} {skills}".strip()
    
    if stage and input_text:
        results = stage_aware_recommend(stage, input_text)
    else:
        results = recommend_course(input_text or skills)
    
    # Save top recommendation
    if not results.empty and 'user_id' in session:
        top_idx = results.iloc[0].name
        top_course_name = results.iloc[0]['course']
        top_score = results.iloc[0]['score']
        
        # Lookup course_id from DB
        from database import get_db_connection, save_recommendation
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id FROM courses WHERE course = ?", (top_course_name,))
        course_row = c.fetchone()
        course_id = course_row[0] if course_row else 1  # fixed: tuple index, default fallback
        conn.close()
        
        save_recommendation(session["user_id"], input_text, course_id, top_score, stage)
    
    return render_template("result.html", courses=results, stage=stage or 'General')

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# Admin Routes
@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect("/login")
    
    # Check if admin
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    users_count, rec_count, courses_count = get_stats()
    return render_template("admin.html", 
                           users_count=users_count, 
                           recommendations_count=rec_count,
                           courses_count=courses_count)

@app.route("/admin/courses")
def admin_courses():
    if "user" not in session:
        return redirect("/login")
    
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    courses = get_all_courses()
    return render_template("admin_courses.html", courses=courses)

@app.route("/admin/add_course", methods=["POST"])
def admin_add_course():
    if "user" not in session:
        return redirect("/login")
    
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    course = request.form["course"]
    level = request.form["level"]
    description = request.form["description"]
    skills = request.form["skills"]
    
    add_course(course, level, description, skills)
    flash("Course added successfully!", "success")
    return redirect("/admin/courses")

@app.route("/admin/delete_course/<int:course_id>")
def admin_delete_course(course_id):
    if "user" not in session:
        return redirect("/login")
    
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    delete_course(course_id)
    flash("Course deleted successfully!", "success")
    return redirect("/admin/courses")

@app.route("/admin/users")
def admin_users():
    if "user" not in session:
        return redirect("/login")
    
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    users = get_all_users()
    return render_template("admin_users.html", users=users)

@app.route("/admin/recommendations")
def admin_recommendations():
    if "user" not in session:
        return redirect("/login")
    
    if not session.get("is_admin"):
        return "Access Denied! Admin only.", 403
    
    recommendations = get_all_recommendations()
    return render_template("admin_recommendations.html", recommendations=recommendations)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
