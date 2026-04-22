import csv
import os
import sqlite3
from werkzeug.security import generate_password_hash


def _load_seed_courses():
    seed_courses = []
    csv_path = "courses.csv"

    if os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                course = (row.get("course") or "").strip()
                level = (row.get("level") or "General").strip() or "General"
                skills = (row.get("skills") or "").strip()

                if not course:
                    continue

                description = f"Recommended learning path for {course}"
                seed_courses.append((course, level, description, skills))

    return seed_courses

def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # Create users table if not exists
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        is_admin INTEGER DEFAULT 0
    )
    """)

    # Create courses table if not exists
    c.execute("""
    CREATE TABLE IF NOT EXISTS courses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT,
        level TEXT,
        description TEXT,
        skills TEXT
    )
    """)

    # Create recommendations table if not exists
    c.execute("""
    CREATE TABLE IF NOT EXISTS recommendations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        skills TEXT,
        stage TEXT DEFAULT 'unknown',
        course_id INTEGER,
        score REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (course_id) REFERENCES courses(id)
    )
    """)
    
    # Safe migration for existing tables
    c.execute("PRAGMA table_info(recommendations)")
    columns = [column[1] for column in c.fetchall()]
    if 'stage' not in columns:
        c.execute("ALTER TABLE recommendations ADD COLUMN stage TEXT DEFAULT 'unknown'")

    # Check if admin exists, if not create default admin
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    admin_user = c.fetchone()
    
    if not admin_user:
        c.execute("INSERT INTO users(username, password, is_admin) VALUES(?,?,?)",
                  ('admin', generate_password_hash('admin123'), 1))

    c.execute("SELECT course FROM courses")
    existing_courses = {row[0].strip().lower() for row in c.fetchall()}

    seed_courses = _load_seed_courses()
    if not seed_courses:
        seed_courses = [
            ('Python Programming', 'Beginner', 'Learn Python from scratch', 'python programming'),
            ('Advanced Python', 'Advanced', 'Master advanced Python concepts', 'python oops'),
            ('Machine Learning', 'Intermediate', 'Introduction to ML algorithms', 'machine learning python'),
            ('Data Science', 'Intermediate', 'Data analysis and visualization', 'python data analysis'),
            ('Web Development', 'Beginner', 'Build websites with HTML CSS JS', 'html css javascript'),
            ('React JS', 'Intermediate', 'Modern frontend framework', 'javascript react'),
            ('SQL Database', 'Beginner', 'Learn database management', 'sql database'),
            ('Deep Learning', 'Advanced', 'Neural networks and AI', 'deep learning python tensorflow'),
            ('Data Structures', 'Intermediate', 'Algorithms and data structures', 'algorithms data structures'),
            ('Cloud Computing', 'Intermediate', 'AWS and cloud services', 'aws cloud'),
            ('DevOps', 'Intermediate', 'CI/CD and automation', 'devops docker kubernetes'),
            ('Mobile Development', 'Intermediate', 'Build Android apps', 'android java kotlin'),
            ('Blockchain', 'Advanced', 'Cryptocurrency and smart contracts', 'blockchain solidity'),
            ('Cybersecurity', 'Intermediate', 'Network security fundamentals', 'security networking'),
            ('Artificial Intelligence', 'Advanced', 'AI and cognitive computing', 'ai machine learning'),
        ]

    courses_to_insert = [
        course for course in seed_courses
        if course[0].strip().lower() not in existing_courses
    ]

    if courses_to_insert:
        c.executemany(
            "INSERT INTO courses(course, level, description, skills) VALUES(?,?,?,?)",
            courses_to_insert
        )

    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    return conn

def get_all_courses():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM courses")
    courses = c.fetchall()
    conn.close()
    return courses

def add_course(course, level, description, skills):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO courses(course, level, description, skills) VALUES(?,?,?,?)",
              (course, level, description, skills))
    conn.commit()
    conn.close()

def delete_course(course_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username FROM users WHERE is_admin = 0")
    users = c.fetchall()
    conn.close()
    return users

def get_all_recommendations():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT r.id, u.username, r.skills, r.stage, c.course, r.score, r.created_at 
        FROM recommendations r
        JOIN users u ON r.user_id = u.id
        JOIN courses c ON r.course_id = c.id
        ORDER BY r.created_at DESC
    """)
    recommendations = c.fetchall()
    conn.close()
    return recommendations

def save_recommendation(user_id, skills, course_id, score, stage=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO recommendations(user_id, skills, stage, course_id, score) VALUES(?,?,?, ?,?)",
              (user_id, skills, stage or 'unknown', course_id, score))
    conn.commit()
    conn.close()


def get_course_id_by_name(course_name):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM courses WHERE lower(course) = lower(?) LIMIT 1", (course_name,))
    row = c.fetchone()
    conn.close()
    return row["id"] if row else None

def get_stats():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin = 0")
    users_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM recommendations")
    rec_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM courses")
    courses_count = c.fetchone()[0]
    
    conn.close()
    return users_count, rec_count, courses_count

def get_user_recommendations(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT r.id, r.skills, r.stage, c.course, c.level, r.score, r.created_at
        FROM recommendations r
        JOIN courses c ON r.course_id = c.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT 30
    """, (user_id,))
    recs = c.fetchall()
    conn.close()
    return recs
