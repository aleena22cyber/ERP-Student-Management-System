from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from functools import wraps
from datetime import date, datetime
from pathlib import Path
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "erp-attendance-demo-secret"
DB = "attendance.db"
STUDENT_FILE = "student list.xlsx"
TARGET = 75.0
SECTION = "K"


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("You do not have permission to open that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def attendance_percent(attended, total):
    return round((attended / total) * 100, 1) if total else 0.0


def import_students_from_excel(conn):
    """
    Reads the Excel file supplied by the teacher.
    Columns used: S#, Enrolno, Name.
    Every student gets a login:
        username = enrollment number
        password = student123
    """
    path = Path(STUDENT_FILE)
    if not path.exists():
        raise FileNotFoundError(
            f"'{STUDENT_FILE}' was not found. Keep the Excel file in the same folder as app.py."
        )

    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"S#", "Enrolno", "Name"}
    if not required.issubset(set(df.columns)):
        raise ValueError("Excel must contain the columns: S#, Enrolno, Name")

    df = df[["S#", "Enrolno", "Name"]].dropna(subset=["Enrolno", "Name"])

    for _, row in df.iterrows():
        enrol_no = str(int(row["Enrolno"])) if isinstance(row["Enrolno"], (int, float)) else str(row["Enrolno"]).strip()
        name = str(row["Name"]).strip()

        existing = conn.execute(
            "SELECT id FROM users WHERE enrollment_no=?",
            (enrol_no,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE users
                SET name=?, role='student', section=?
                WHERE enrollment_no=?
            """, (name, SECTION, enrol_no))
        else:
            conn.execute("""
                INSERT INTO users
                (username,password_hash,name,role,section,enrollment_no)
                VALUES(?,?,?,?,?,?)
            """, (
                enrol_no,
                generate_password_hash("student123"),
                name,
                "student",
                SECTION,
                enrol_no
            ))


def send_external_alert(conn, student_id, subject, message):
    """Send to whichever external channels are configured; in-app alert remains independent."""
    try:
        from notification_service import send_configured_notifications
        student = conn.execute(
            "SELECT name,email,phone FROM users WHERE id=?", (student_id,)
        ).fetchone()
        if student:
            results = send_configured_notifications(
                student_name=student["name"], email=student["email"], phone=student["phone"],
                subject=subject, message=message
            )
            app.logger.info("External notification results for %s: %s", student["name"], results)
    except Exception as exc:
        app.logger.warning("External notification could not be sent: %s", exc)


def create_low_attendance_notification(conn, student_id, course_code, percent):
    if percent < TARGET:
        message = (
            f"Attendance Alert: Your attendance in {course_code} is {percent}%, "
            f"which is below the required {TARGET:.0f}%."
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        exists = conn.execute("""
            SELECT id FROM notifications
            WHERE student_id=? AND message=? AND date(created_at)=date(?)
        """, (student_id, message, now)).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO notifications(student_id,message,created_at)
                VALUES(?,?,?)
            """, (student_id, message, now))
            send_external_alert(conn, student_id, "Attendance Shortage Alert", message)


def create_absence_notification(conn, student_id, course_code, course_name, attendance_date):
    """Create one in-app absence alert per student/course/date."""
    message = (
        f"Absence Alert: You were marked absent for {course_name} "
        f"({course_code}) on {attendance_date}. If this is incorrect, please contact your faculty."
    )
    exists = conn.execute("""
        SELECT id FROM notifications
        WHERE student_id=? AND message=?
    """, (student_id, message)).fetchone()

    if not exists:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO notifications(student_id,message,created_at)
            VALUES(?,?,?)
        """, (student_id, message, now))
        # Keep the in-app notification and try external channels independently.
        send_external_alert(conn, student_id, "Class Absence Notification", message)



def seed_demo_attendance(conn):
    """
    Creates a small amount of demo attendance only if attendance table is empty.
    The first student is deliberately below 75% in AI303 so the notification
    can be demonstrated immediately.
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM attendance").fetchone()["c"]
    if count:
        return

    students = conn.execute("""
        SELECT id FROM users WHERE role='student' ORDER BY CAST(enrollment_no AS INTEGER)
    """).fetchall()

    courses = conn.execute("SELECT id,code FROM courses ORDER BY code").fetchall()
    if not students or not courses:
        return

    # 10 sessions per subject. First student: 7/10 AI303 => 70%.
    dates = [
        "2026-09-01", "2026-09-03", "2026-09-05", "2026-09-08", "2026-09-10",
        "2026-09-12", "2026-09-15", "2026-09-17", "2026-09-19", "2026-09-22"
    ]

    for student_index, student in enumerate(students):
        for course_index, course in enumerate(courses):
            for i, dt in enumerate(dates):
                if student_index == 0 and course["code"] == "AI303":
                    status = "Present" if i < 7 else "Absent"
                else:
                    # Most demo students start above the threshold.
                    status = "Present" if ((i + student_index + course_index) % 5 != 0) else "Absent"

                conn.execute("""
                    INSERT OR IGNORE INTO attendance
                    (student_id,course_id,attendance_date,status)
                    VALUES(?,?,?,?)
                """, (student["id"], course["id"], dt, status))

    # Generate initial low-attendance notification for the first student.
    first = students[0]
    ai303 = conn.execute("SELECT * FROM courses WHERE code='AI303'").fetchone()
    stats = conn.execute("""
        SELECT
            SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS attended,
            COUNT(*) AS total
        FROM attendance
        WHERE student_id=? AND course_id=?
    """, (first["id"], ai303["id"])).fetchone()

    percent = attendance_percent(stats["attended"] or 0, stats["total"] or 0)
    create_low_attendance_notification(conn, first["id"], "AI303", percent)


def create_assignment_reminders_for_student(conn, student_id):
    """Create a portal alert when an assignment is due within the next five days."""
    today = date.today()
    assignments = conn.execute("""
        SELECT a.id, a.title, a.due_date, c.code, c.name
        FROM assignments a
        JOIN courses c ON c.id = a.course_id
        WHERE c.section=?
    """, (SECTION,)).fetchall()

    for assignment in assignments:
        try:
            due_date = date.fromisoformat(assignment["due_date"])
        except (TypeError, ValueError):
            continue
        days_left = (due_date - today).days
        # Show a reminder when the deadline is 0 to 5 days away, including
        # assignments already inside the five-day window when first created.
        if not 0 <= days_left <= 5:
            continue

        already_created = conn.execute("""
            SELECT id FROM assignment_reminders
            WHERE assignment_id=? AND student_id=?
        """, (assignment["id"], student_id)).fetchone()
        if already_created:
            continue

        message = (
            f"Assignment Reminder: \"{assignment['title']}\" for "
            f"{assignment['code']} - {assignment['name']} is due on "
            f"{assignment['due_date']}. "
            f"{f'{days_left} day(s) left.' if days_left > 0 else 'The deadline is today.'}"
        )
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute("""
            INSERT INTO notifications(student_id, message, created_at)
            VALUES(?,?,?)
        """, (student_id, message, created_at))
        conn.execute("""
            INSERT INTO assignment_reminders
            (assignment_id, student_id, notification_id, reminder_date)
            VALUES(?,?,?,?)
        """, (assignment["id"], student_id, cursor.lastrowid, today.isoformat()))



def create_fee_notification(conn, student_id, fee_id, event_key, event_type, subject, message):
    """Create one fee event safely; repeated page loads must not duplicate it."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT OR IGNORE INTO fee_notification_log "
        "(fee_id, student_id, event_key, event_type, created_at) VALUES (?, ?, ?, ?, ?)",
        (fee_id, student_id, event_key, event_type, now)
    )
    # If this event key was already recorded, don't create another portal notification
    # and don't send another email.
    if cur.rowcount == 0:
        return False
    conn.execute(
        "INSERT INTO notifications(student_id, message, created_at) VALUES (?, ?, ?)",
        (student_id, message, now)
    )
    send_external_alert(conn, student_id, subject, message)
    return True


def process_fee_reminders(conn, today=None):
    """Run date-based fee reminders whenever a portal page is opened; duplicate tiers are suppressed."""
    today = today or date.today()
    rows = conn.execute("""
        SELECT f.*, u.name
        FROM fees f JOIN users u ON u.id=f.student_id
        WHERE f.status!='PAID'
    """).fetchall()
    for fee in rows:
        try:
            due = date.fromisoformat(fee["due_date"])
        except (TypeError, ValueError):
            continue
        days_left = (due - today).days
        balance = round(float(fee["amount"]) - float(fee["amount_paid"]), 2)
        if days_left in (7,  3, 1):
            key = f"fee:{fee['id']}:before:{days_left}"
            msg = (f"Fee Payment Reminder: {fee['title']} of Rs. {balance:.2f} is due "
                   f"on {fee['due_date']} ({days_left} day(s) remaining).")
            create_fee_notification(conn, fee["student_id"], fee["id"], key, "DUE_REMINDER",
                                    "Fee Payment Reminder", msg)
        elif days_left < 0:
            days_overdue = abs(days_left)
            tiers = [t for t in (1, 7, 14, 30) if days_overdue >= t]
            if tiers:
                tier = max(tiers)
                key = f"fee:{fee['id']}:overdue:{tier}"
                msg = (f"Unpaid Fee Alert: {fee['title']} has an outstanding balance of "
                       f"Rs. {balance:.2f}. The due date was {fee['due_date']} "
                       f"({days_overdue} day(s) overdue).")
                create_fee_notification(conn, fee["student_id"], fee["id"], key, "OVERDUE_ALERT",
                                        "Unpaid Fee Overdue", msg)


def init_db():
    conn = get_db()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('teacher','student')),
        section TEXT,
        enrollment_no TEXT UNIQUE,
        email TEXT,
        phone TEXT
    );

    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        section TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        course_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('Present','Absent')),
        UNIQUE(student_id, course_id, attendance_date),
        FOREIGN KEY(student_id) REFERENCES users(id),
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        FOREIGN KEY(student_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        course_id INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(course_id) REFERENCES courses(id)
    );

    CREATE TABLE IF NOT EXISTS assignment_reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        notification_id INTEGER NOT NULL,
        reminder_date TEXT NOT NULL,
        UNIQUE(assignment_id, student_id),
        FOREIGN KEY(assignment_id) REFERENCES assignments(id),
        FOREIGN KEY(student_id) REFERENCES users(id),
        FOREIGN KEY(notification_id) REFERENCES notifications(id)
    );

    CREATE TABLE IF NOT EXISTS fees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        amount REAL NOT NULL CHECK(amount > 0),
        amount_paid REAL NOT NULL DEFAULT 0,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PARTIAL','PAID')),
        created_at TEXT NOT NULL,
        FOREIGN KEY(student_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS fee_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fee_id INTEGER NOT NULL,
        amount REAL NOT NULL CHECK(amount > 0),
        method TEXT,
        reference TEXT,
        paid_at TEXT NOT NULL,
        FOREIGN KEY(fee_id) REFERENCES fees(id)
    );

    CREATE TABLE IF NOT EXISTS fee_notification_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fee_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        event_key TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(fee_id) REFERENCES fees(id),
        FOREIGN KEY(student_id) REFERENCES users(id)
    );
    """)

    # Safe migration for databases created by an earlier version.
    user_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if "phone" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")

    # Teacher account.
    teacher = conn.execute(
        "SELECT id FROM users WHERE username='teacher1'"
    ).fetchone()

    if not teacher:
        conn.execute("""
            INSERT INTO users
            (username,password_hash,name,role,section,enrollment_no)
            VALUES(?,?,?,?,?,?)
        """, (
            "teacher1",
            generate_password_hash("teacher123"),
            "ERP Attendance Teacher",
            "teacher",
            SECTION,
            None
        ))

    # Subjects based on the portal screenshots.
    courses = [
        ("AI302", "Computer Networks", SECTION),
        ("AI303", "Blockchain Technology", SECTION),
        ("HS301", "Constitution of India", SECTION),
    ]

    for code, name, section in courses:
        conn.execute("""
            INSERT OR IGNORE INTO courses(code,name,section)
            VALUES(?,?,?)
        """, (code, name, section))

    conn.commit()

    # Import actual students from the Excel file.
    import_students_from_excel(conn)
    conn.commit()

    seed_demo_attendance(conn)
    conn.commit()
    conn.close()


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["section"] = user["section"]
            session["enrollment_no"] = user["enrollment_no"]
            return redirect(url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required()
def dashboard():
    return redirect(
        url_for("teacher_dashboard")
        if session["role"] == "teacher"
        else url_for("student_dashboard")
    )


@app.route("/teacher")
@login_required("teacher")
def teacher_dashboard():
    conn = get_db()

    students = conn.execute("""
        SELECT id, name, username, section, enrollment_no
        FROM users
        WHERE role='student' AND section=?
        ORDER BY CAST(enrollment_no AS INTEGER)
    """, (SECTION,)).fetchall()

    courses = conn.execute("""
        SELECT * FROM courses WHERE section=? ORDER BY code
    """, (SECTION,)).fetchall()

    summaries = {}
    for student in students:
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS attended,
                COUNT(*) AS total
            FROM attendance
            WHERE student_id=?
        """, (student["id"],)).fetchone()

        summaries[student["id"]] = attendance_percent(
            row["attended"] or 0, row["total"] or 0
        )

    conn.close()
    return render_template(
        "teacher_dashboard.html",
        students=students,
        courses=courses,
        summaries=summaries
    )


@app.route("/teacher/attendance", methods=["GET", "POST"])
@login_required("teacher")
def manage_attendance():
    conn = get_db()

    courses = conn.execute("""
        SELECT * FROM courses WHERE section=? ORDER BY code
    """, (SECTION,)).fetchall()

    course_id = request.values.get("course_id", type=int)
    attendance_date = (
        request.values.get("attendance_date")
        or date.today().isoformat()
    )

    if not course_id and courses:
        course_id = courses[0]["id"]

    course = conn.execute("""
        SELECT * FROM courses WHERE id=? AND section=?
    """, (course_id, SECTION)).fetchone() if course_id else None

    students = conn.execute("""
        SELECT id, name, username, enrollment_no
        FROM users
        WHERE role='student' AND section=?
        ORDER BY CAST(enrollment_no AS INTEGER)
    """, (SECTION,)).fetchall()

    if request.method == "POST":
        newly_absent = []
        for student in students:
            status = request.form.get(
                f"status_{student['id']}", "Absent"
            )

            previous = conn.execute("""
                SELECT status FROM attendance
                WHERE student_id=? AND course_id=? AND attendance_date=?
            """, (student["id"], course_id, attendance_date)).fetchone()

            if status == "Absent" and (not previous or previous["status"] != "Absent"):
                newly_absent.append(student["id"])

            conn.execute("""
                INSERT INTO attendance
                (student_id,course_id,attendance_date,status)
                VALUES(?,?,?,?)
                ON CONFLICT(student_id,course_id,attendance_date)
                DO UPDATE SET status=excluded.status
            """, (
                student["id"],
                course_id,
                attendance_date,
                status
            ))

        # Recalculate attendance and trigger notification.
        for student in students:
            stats = conn.execute("""
                SELECT
                    SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS attended,
                    COUNT(*) AS total
                FROM attendance
                WHERE student_id=? AND course_id=?
            """, (student["id"], course_id)).fetchone()

            percent = attendance_percent(
                stats["attended"] or 0,
                stats["total"] or 0
            )

            create_low_attendance_notification(
                conn,
                student["id"],
                course["code"],
                percent
            )

        # Send one absence alert when a student is newly marked Absent for this class.
        for student_id in newly_absent:
            create_absence_notification(
                conn,
                student_id,
                course["code"],
                course["name"],
                attendance_date
            )

        conn.commit()
        conn.close()

        flash(
            f"Attendance saved for {course['code']} on {attendance_date}.",
            "success"
        )

        return redirect(url_for(
            "manage_attendance",
            course_id=course_id,
            attendance_date=attendance_date
        ))

    existing = {}
    if course:
        rows = conn.execute("""
            SELECT student_id,status
            FROM attendance
            WHERE course_id=? AND attendance_date=?
        """, (course_id, attendance_date)).fetchall()

        existing = {
            row["student_id"]: row["status"]
            for row in rows
        }

    conn.close()

    return render_template(
        "manage_attendance.html",
        courses=courses,
        course=course,
        students=students,
        existing=existing,
        attendance_date=attendance_date
    )


@app.route("/teacher/contacts", methods=["GET", "POST"])
@login_required("teacher")
def manage_contacts():
    """Teacher-only page for entering contact details for the demo/test recipients."""
    conn = get_db()
    if request.method == "POST":
        student_id = request.form.get("student_id", type=int)
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        conn.execute("UPDATE users SET email=?, phone=? WHERE id=? AND role='student'", (email or None, phone or None, student_id))
        conn.commit()
        flash("Student contact details saved.", "success")
        conn.close()
        return redirect(url_for("manage_contacts"))
    students = conn.execute("""
        SELECT id, name, enrollment_no, email, phone FROM users
        WHERE role='student' AND section=? ORDER BY CAST(enrollment_no AS INTEGER)
    """, (SECTION,)).fetchall()
    conn.close()
    return render_template("teacher_contacts.html", students=students)


@app.route("/teacher/assignments", methods=["GET", "POST"])
@login_required("teacher")
def manage_assignments():
    conn = get_db()
    courses = conn.execute(
        "SELECT id, code, name FROM courses WHERE section=? ORDER BY code",
        (SECTION,)
    ).fetchall()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        course_id = request.form.get("course_id", type=int)
        due_date = request.form.get("due_date", "").strip()
        description = request.form.get("description", "").strip()

        if not title or not course_id or not due_date:
            flash("Please enter the assignment title, subject, and due date.", "error")
        else:
            try:
                date.fromisoformat(due_date)
                course = conn.execute(
                    "SELECT id FROM courses WHERE id=? AND section=?",
                    (course_id, SECTION)
                ).fetchone()
                if not course:
                    flash("Please select a valid subject.", "error")
                elif due_date < date.today().isoformat():
                    flash("The due date cannot be in the past.", "error")
                else:
                    conn.execute("""
                        INSERT INTO assignments(title, course_id, due_date, description, created_at)
                        VALUES(?,?,?,?,?)
                    """, (title, course_id, due_date, description,
                          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    conn.commit()
                    flash("Assignment added. Students will receive a portal reminder 5 days before the deadline.", "success")
                    conn.close()
                    return redirect(url_for("manage_assignments"))
            except ValueError:
                flash("Please choose a valid due date.", "error")

    assignments = conn.execute("""
        SELECT a.id, a.title, a.due_date, a.description, c.code, c.name
        FROM assignments a JOIN courses c ON c.id=a.course_id
        WHERE c.section=?
        ORDER BY a.due_date, a.id DESC
    """, (SECTION,)).fetchall()
    conn.close()
    return render_template("teacher_assignments.html", courses=courses, assignments=assignments)


@app.route("/teacher/assignments/delete/<int:assignment_id>", methods=["POST"])
@login_required("teacher")
def delete_assignment(assignment_id):
    conn = get_db()
    assignment = conn.execute("""
        SELECT a.id FROM assignments a JOIN courses c ON c.id=a.course_id
        WHERE a.id=? AND c.section=?
    """, (assignment_id, SECTION)).fetchone()
    if assignment:
        conn.execute("DELETE FROM assignment_reminders WHERE assignment_id=?", (assignment_id,))
        conn.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
        conn.commit()
        flash("Assignment deleted.", "success")
    conn.close()
    return redirect(url_for("manage_assignments"))


@app.route("/student")
@login_required("student")
def student_dashboard():
    conn = get_db()
    process_fee_reminders(conn)
    conn.commit()

    courses = conn.execute("""
        SELECT * FROM courses WHERE section=? ORDER BY code
    """, (SECTION,)).fetchall()

    cards = []

    for course in courses:
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS attended,
                COUNT(*) AS total
            FROM attendance
            WHERE student_id=? AND course_id=?
        """, (session["user_id"], course["id"])).fetchone()

        attended = row["attended"] or 0
        total = row["total"] or 0
        percent = attendance_percent(attended, total)

        cards.append({
            "code": course["code"],
            "name": course["name"],
            "attended": attended,
            "total": total,
            "percent": percent,
            "status": "SAFE" if percent >= TARGET else "WARNING"
        })

    overall = conn.execute("""
        SELECT
            SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) AS attended,
            COUNT(*) AS total
        FROM attendance
        WHERE student_id=?
    """, (session["user_id"],)).fetchone()

    overall_percent = attendance_percent(
        overall["attended"] or 0,
        overall["total"] or 0
    )

    # Check assignment deadlines whenever the student opens the portal.
    create_assignment_reminders_for_student(conn, session["user_id"])
    conn.commit()

    notifications = conn.execute("""
        SELECT * FROM notifications
        WHERE student_id=?
        ORDER BY id DESC
        LIMIT 20
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template(
        "student_dashboard.html",
        cards=cards,
        overall_percent=overall_percent,
        notifications=notifications,
        target=TARGET
    )


@app.route("/student/assignments")
@login_required("student")
def student_assignments():
    conn = get_db()
    process_fee_reminders(conn)
    conn.commit()
    # Generate due-in-five-days reminders whenever the student opens this page too.
    create_assignment_reminders_for_student(conn, session["user_id"])
    conn.commit()

    assignments = conn.execute("""
        SELECT a.id, a.title, a.due_date, a.description, c.code, c.name
        FROM assignments a
        JOIN courses c ON c.id = a.course_id
        WHERE c.section=?
        ORDER BY a.due_date, a.id DESC
    """, (SECTION,)).fetchall()

    today = date.today()
    assignment_rows = []
    for assignment in assignments:
        item = dict(assignment)
        try:
            days_left = (date.fromisoformat(item["due_date"]) - today).days
        except (TypeError, ValueError):
            days_left = None
        item["days_left"] = days_left
        assignment_rows.append(item)

    conn.close()
    return render_template("student_assignments.html", assignments=assignment_rows)



@app.route("/teacher/fees", methods=["GET", "POST"])
@login_required("teacher")
def manage_fees():
    conn = get_db()
    students = conn.execute("""
        SELECT id, name, enrollment_no, email FROM users
        WHERE role='student' AND section=?
        ORDER BY CAST(enrollment_no AS INTEGER)
    """, (SECTION,)).fetchall()

    if request.method == "POST":
        student_id = request.form.get("student_id", type=int)
        title = request.form.get("title", "").strip()
        due_date = request.form.get("due_date", "").strip()
        amount_raw = request.form.get("amount", "").strip()
        try:
            amount = round(float(amount_raw), 2)
            parsed_due = date.fromisoformat(due_date)
            student = conn.execute(
                "SELECT id FROM users WHERE id=? AND role='student' AND section=?",
                (student_id, SECTION)
            ).fetchone()
            if not student or not title or amount <= 0:
                raise ValueError
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute("""
                INSERT INTO fees(student_id,title,amount,due_date,created_at)
                VALUES(?,?,?,?,?)
            """, (student_id, title, amount, parsed_due.isoformat(), now))
            msg = f"New Fee Assigned: {title}. Amount: Rs. {amount:.2f}. Payment deadline: {parsed_due.isoformat()}."
            create_fee_notification(conn, student_id, cur.lastrowid,
                                    f"fee:{cur.lastrowid}:assigned", "FEE_ASSIGNED",
                                    "New Fee Assigned", msg)
            conn.commit()
            flash("Fee assigned. The student has an in-portal notification and an email will be sent if their Gmail is configured.", "success")
            conn.close()
            return redirect(url_for("manage_fees"))
        except (ValueError, TypeError):
            flash("Enter a student, fee title, positive amount, and valid due date.", "error")

    fees = conn.execute("""
        SELECT f.*, u.name AS student_name, u.enrollment_no
        FROM fees f JOIN users u ON u.id=f.student_id
        WHERE u.section=? ORDER BY f.due_date, f.id DESC
    """, (SECTION,)).fetchall()
    conn.close()
    return render_template("teacher_fees.html", students=students, fees=fees, today=date.today().isoformat())


@app.route("/teacher/fees/<int:fee_id>/payment", methods=["POST"])
@login_required("teacher")
def record_fee_payment(fee_id):
    conn = get_db()
    fee = conn.execute("""
        SELECT f.*, u.name FROM fees f JOIN users u ON u.id=f.student_id
        WHERE f.id=? AND u.section=?
    """, (fee_id, SECTION)).fetchone()
    if not fee:
        conn.close()
        flash("Fee record not found.", "error")
        return redirect(url_for("manage_fees"))
    try:
        amount = round(float(request.form.get("amount", "")), 2)
        if amount <= 0 or amount > round(fee["amount"] - fee["amount_paid"], 2):
            raise ValueError
    except (ValueError, TypeError):
        conn.close()
        flash("Enter a valid payment amount not greater than the remaining balance.", "error")
        return redirect(url_for("manage_fees"))

    method = request.form.get("method", "Not specified").strip()
    reference = request.form.get("reference", "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO fee_payments(fee_id,amount,method,reference,paid_at)
        VALUES(?,?,?,?,?)
    """, (fee_id, amount, method, reference or None, now))
    paid_total = round(fee["amount_paid"] + amount, 2)
    new_status = "PAID" if paid_total >= fee["amount"] else "PARTIAL"
    conn.execute("UPDATE fees SET amount_paid=?, status=? WHERE id=?",
                 (paid_total, new_status, fee_id))
    balance = round(fee["amount"] - paid_total, 2)
    msg = (f"Payment Recorded: We recorded Rs. {amount:.2f} for {fee['title']}. "
           f"Total paid: Rs. {paid_total:.2f}. Remaining balance: Rs. {balance:.2f}. "
           f"Status: {new_status}.")
    create_fee_notification(conn, fee["student_id"], fee_id,
                            f"fee:{fee_id}:payment:{conn.execute('SELECT last_insert_rowid()').fetchone()[0]}",
                            "PAYMENT_RECORDED", "Fee Payment Confirmation", msg)
    conn.commit()
    conn.close()
    flash("Payment recorded and student notified.", "success")
    return redirect(url_for("manage_fees"))


@app.route("/student/fees")
@login_required("student")
def student_fees():
    conn = get_db()
    process_fee_reminders(conn)
    conn.commit()
    fees = conn.execute("""
        SELECT * FROM fees WHERE student_id=? ORDER BY due_date, id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("student_fees.html", fees=fees, today=date.today().isoformat())


@app.route("/student/history/<code>")
@login_required("student")
def student_history(code):
    conn = get_db()

    course = conn.execute("""
        SELECT * FROM courses
        WHERE code=? AND section=?
    """, (code, SECTION)).fetchone()

    if not course:
        conn.close()
        return "Course not found", 404

    records = conn.execute("""
        SELECT attendance_date,status
        FROM attendance
        WHERE student_id=? AND course_id=?
        ORDER BY attendance_date DESC
    """, (session["user_id"], course["id"])).fetchall()

    conn.close()

    return render_template(
        "student_history.html",
        course=course,
        records=records
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
