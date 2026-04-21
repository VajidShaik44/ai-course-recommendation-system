import sqlite3
from werkzeug.security import generate_password_hash

# ---------------- INIT DB ---------------- #
def init_db():
    conn = sqlite3.connect("students.db")
    c = conn.cursor()

    # USERS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        is_admin INTEGER DEFAULT 0
    )
    """)

    # COURSES TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS courses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course TEXT,
        level TEXT,
        description TEXT,
        skills TEXT
    )
    """)

    # RECOMMENDATIONS TABLE
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

    # SAFE MIGRATION
    c.execute("PRAGMA table_info(recommendations)")
    columns = [col[1] for col in c.fetchall()]
    if 'stage' not in columns:
        c.execute("ALTER TABLE recommendations ADD COLUMN stage TEXT DEFAULT 'unknown'")

    # DEFAULT ADMIN (ONLY IF NOT EXISTS)
    c.execute("SELECT id FROM users WHERE username = ?", ("admin",))
    if not c.fetchone():
        c.execute(
            "INSERT INTO users(username, password, is_admin) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), 1)
        )

    # INSERT COURSES ONLY IF EMPTY
    c.execute("SELECT COUNT(*) FROM courses")
    if c.fetchone()[0] == 0:
        sample_courses = [
            ('Python Programming', 'Beginner', 'Learn Python from scratch', 'python programming'),
            ('Machine Learning', 'Intermediate', 'ML basics', 'machine learning python'),
            ('Data Science', 'Intermediate', 'Data analysis', 'python pandas numpy'),
            ('Web Development', 'Beginner', 'HTML CSS JS', 'html css javascript'),
            ('DevOps', 'Intermediate', 'CI/CD pipelines', 'docker kubernetes aws'),
        ]

        c.executemany(
            "INSERT INTO courses(course, level, description, skills) VALUES(?,?,?,?)",
            sample_courses
        )

    conn.commit()
    conn.close()


# ---------------- CONNECTION ---------------- #
def get_db_connection():
    conn = sqlite3.connect("students.db")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- USER HELPERS ---------------- #

def user_exists(username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    return user is not None


def create_user(username, password_hash):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO users(username, password) VALUES (?, ?)", (username, password_hash))
    conn.commit()
    conn.close()


def get_user(username):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, password FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    return user


# ---------------- RECOMMENDATION ---------------- #

def save_recommendation(user_id, skills, course_id, score, stage=None):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute(
        "INSERT INTO recommendations(user_id, skills, stage, course_id, score) VALUES(?,?,?,?,?)",
        (user_id, skills, stage or 'unknown', course_id, score)
    )

    conn.commit()
    conn.close()


def get_user_recommendations(user_id):
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        SELECT r.id, r.skills, r.stage, c.course, r.score, r.created_at
        FROM recommendations r
        JOIN courses c ON r.course_id = c.id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT 30
    """, (user_id,))

    data = c.fetchall()
    conn.close()
    return data