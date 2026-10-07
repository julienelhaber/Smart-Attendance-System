import sqlite3
from datetime import datetime

DB_NAME = "attendance.db"
OLD_PARENT_COLUMN = "fa" + "ther_name"


def connect_db():
    return sqlite3.connect(DB_NAME)


def create_tables():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        student_email TEXT NOT NULL,
        department TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS deleted_students (
        id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        student_email TEXT NOT NULL,
        department TEXT,
        deleted_date TEXT,
        deleted_time TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        full_name TEXT,
        date TEXT,
        check_in TEXT,
        check_out TEXT,
        total_hours TEXT,
        status TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attendance_id INTEGER,
        student_id INTEGER,
        full_name TEXT,
        date TEXT,
        time TEXT,
        action TEXT,
        total_hours TEXT
    )
    """)

    # Add missing columns if an older database is used.
    cursor.execute("PRAGMA table_info(attendance)")
    columns = [column[1] for column in cursor.fetchall()]

    if "check_in" not in columns:
        cursor.execute("ALTER TABLE attendance ADD COLUMN check_in TEXT")
    if "check_out" not in columns:
        cursor.execute("ALTER TABLE attendance ADD COLUMN check_out TEXT")
    if "total_hours" not in columns:
        cursor.execute("ALTER TABLE attendance ADD COLUMN total_hours TEXT")
    if "status" not in columns:
        cursor.execute("ALTER TABLE attendance ADD COLUMN status TEXT")

    # Clean/migrate old database versions and remove the previous parent-name column completely.
    cursor.execute("PRAGMA table_info(students)")
    student_columns = [column[1] for column in cursor.fetchall()]
    if "student_email" not in student_columns or OLD_PARENT_COLUMN in student_columns:
        email_expr = "student_email" if "student_email" in student_columns else "''"
        if OLD_PARENT_COLUMN in student_columns:
            email_expr = f"COALESCE(NULLIF({email_expr}, ''), " + OLD_PARENT_COLUMN + ", '')"
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS students_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            student_email TEXT NOT NULL,
            department TEXT
        )
        """)
        cursor.execute(f"""
        INSERT INTO students_new (id, full_name, student_email, department)
        SELECT id, full_name, {email_expr}, department FROM students
        """)
        cursor.execute("DROP TABLE students")
        cursor.execute("ALTER TABLE students_new RENAME TO students")

    cursor.execute("PRAGMA table_info(deleted_students)")
    deleted_columns = [column[1] for column in cursor.fetchall()]
    if "student_email" not in deleted_columns or OLD_PARENT_COLUMN in deleted_columns:
        email_expr = "student_email" if "student_email" in deleted_columns else "''"
        if OLD_PARENT_COLUMN in deleted_columns:
            email_expr = f"COALESCE(NULLIF({email_expr}, ''), " + OLD_PARENT_COLUMN + ", '')"
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS deleted_students_new (
            id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            student_email TEXT NOT NULL,
            department TEXT,
            deleted_date TEXT,
            deleted_time TEXT
        )
        """)
        cursor.execute(f"""
        INSERT INTO deleted_students_new (id, full_name, student_email, department, deleted_date, deleted_time)
        SELECT id, full_name, {email_expr}, department, deleted_date, deleted_time FROM deleted_students
        """)
        cursor.execute("DROP TABLE deleted_students")
        cursor.execute("ALTER TABLE deleted_students_new RENAME TO deleted_students")

    # Backfill event logs from old attendance session rows if needed.
    cursor.execute("SELECT COUNT(*) FROM attendance_events")
    event_count = cursor.fetchone()[0]

    if event_count == 0:
        cursor.execute("""
        SELECT id, student_id, full_name, date, check_in, check_out, total_hours
        FROM attendance
        ORDER BY id ASC
        """)
        old_records = cursor.fetchall()

        for attendance_id, student_id, full_name, date, check_in, check_out, total_hours in old_records:
            if check_in:
                cursor.execute("""
                INSERT INTO attendance_events
                (attendance_id, student_id, full_name, date, time, action, total_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (attendance_id, student_id, full_name, date, check_in, "Check In", "0h 0m 0s"))

            if check_out:
                cursor.execute("""
                INSERT INTO attendance_events
                (attendance_id, student_id, full_name, date, time, action, total_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (attendance_id, student_id, full_name, date, check_out, "Check Out", total_hours or "0h 0m 0s"))

    conn.commit()
    conn.close()


# ======================= STUDENTS =======================

def add_student(full_name, student_email, department):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO students (full_name, student_email, department)
    VALUES (?, ?, ?)
    """, (full_name, student_email, department))

    conn.commit()
    student_db_id = cursor.lastrowid
    conn.close()
    return student_db_id


def get_students():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, full_name, student_email, department
    FROM students
    ORDER BY id ASC
    """)

    students = cursor.fetchall()
    conn.close()
    return students


def student_exists(student_id):
    return get_student_by_id(student_id)


def get_student_by_id(student_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, full_name, student_email, department
    FROM students
    WHERE id = ?
    """, (student_id,))

    student = cursor.fetchone()
    conn.close()
    return student


def get_student_by_email(student_email):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, full_name, student_email, department
    FROM students
    WHERE LOWER(student_email) = LOWER(?)
    """, (student_email.strip(),))

    student = cursor.fetchone()
    conn.close()
    return student


def delete_student(student_id):
    """
    Move the student from active students to deleted_students.
    Attendance logs stay saved and still appear in admin reports.
    """
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, full_name, student_email, department
    FROM students
    WHERE id = ?
    """, (student_id,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return False

    now = datetime.now()
    deleted_date = now.strftime("%Y-%m-%d")
    deleted_time = now.strftime("%H:%M:%S")

    cursor.execute("""
    INSERT OR REPLACE INTO deleted_students
    (id, full_name, student_email, department, deleted_date, deleted_time)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (student[0], student[1], student[2], student[3], deleted_date, deleted_time))

    cursor.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()
    return True


def get_deleted_students():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, full_name, student_email, department, deleted_date, deleted_time
    FROM deleted_students
    ORDER BY deleted_date DESC, deleted_time DESC, id DESC
    """)

    deleted_students = cursor.fetchall()
    conn.close()
    return deleted_students


# ======================= ATTENDANCE =======================

def format_seconds(total_seconds):
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}h {minutes}m {seconds}s"


def parse_total_hours(time_string):
    if not time_string:
        return 0

    try:
        parts = time_string.split()
        hours = int(parts[0].replace("h", ""))
        minutes = int(parts[1].replace("m", ""))
        seconds = int(parts[2].replace("s", ""))
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def add_attendance_event(attendance_id, student_id, full_name, date, time, action, total_hours="0h 0m 0s"):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO attendance_events
    (attendance_id, student_id, full_name, date, time, action, total_hours)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (attendance_id, student_id, full_name, date, time, action, total_hours))
    conn.commit()
    conn.close()


def get_active_checkins_count():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT COUNT(*)
    FROM attendance
    WHERE status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    """)
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_active_attendance_sessions():
    """
    Return all currently active check-in sessions for the admin page.
    Each row includes: attendance_id, student_id, full_name, date, check_in, status.
    """
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, student_id, full_name, date, check_in, status
    FROM attendance
    WHERE status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    ORDER BY date DESC, check_in DESC, id DESC
    """)

    records = cursor.fetchall()
    conn.close()
    return records


def check_out_attendance_session(attendance_id):
    """
    Admin manual check-out for a specific active attendance session.
    It closes the selected session and adds a Check Out event to attendance_events.
    """
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, student_id, full_name, date, check_in
    FROM attendance
    WHERE id = ?
      AND status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    """, (attendance_id,))

    open_record = cursor.fetchone()

    if not open_record:
        conn.close()
        return "No Active Check In"

    attendance_id, student_id, full_name, check_in_date, check_in_time = open_record

    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")

    check_in_datetime = datetime.strptime(
        f"{check_in_date} {check_in_time}",
        "%Y-%m-%d %H:%M:%S"
    )
    check_out_datetime = datetime.strptime(
        f"{current_date} {current_time}",
        "%Y-%m-%d %H:%M:%S"
    )

    total_seconds = (check_out_datetime - check_in_datetime).total_seconds()
    total_time = format_seconds(total_seconds)

    cursor.execute("""
    UPDATE attendance
    SET check_out = ?, total_hours = ?, status = ?
    WHERE id = ?
    """, (current_time, total_time, "Checked Out", attendance_id))

    cursor.execute("""
    INSERT INTO attendance_events
    (attendance_id, student_id, full_name, date, time, action, total_hours)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (attendance_id, student_id, full_name, current_date, current_time, "Check Out", total_time))

    conn.commit()
    conn.close()
    return "Checked Out"


def get_attendance_events(student_id=None):
    """
    Return every action log separately with full session details.
    Each row includes: student_id, full_name, date, event_time, action,
    total_hours, session_check_in, session_check_out, session_status.
    """
    conn = connect_db()
    cursor = conn.cursor()

    if student_id in (None, "", "All Students"):
        cursor.execute("""
        SELECT
            e.student_id,
            e.full_name,
            e.date,
            e.time,
            e.action,
            e.total_hours,
            a.check_in,
            a.check_out,
            a.status
        FROM attendance_events e
        LEFT JOIN attendance a ON e.attendance_id = a.id
        ORDER BY e.date DESC, e.time DESC, e.id DESC
        """)
    else:
        cursor.execute("""
        SELECT
            e.student_id,
            e.full_name,
            e.date,
            e.time,
            e.action,
            e.total_hours,
            a.check_in,
            a.check_out,
            a.status
        FROM attendance_events e
        LEFT JOIN attendance a ON e.attendance_id = a.id
        WHERE e.student_id = ?
        ORDER BY e.date DESC, e.time DESC, e.id DESC
        """, (student_id,))

    records = cursor.fetchall()
    conn.close()
    return records


def has_active_attendance(student_id):
    return get_active_attendance(student_id) is not None


def check_in_student(student_id):
    """
    Start a new attendance session only when the student has no open session.
    If the student is already checked in, keep the existing session open.
    """
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id
    FROM attendance
    WHERE student_id = ?
      AND status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    ORDER BY id DESC
    LIMIT 1
    """, (student_id,))

    active = cursor.fetchone()
    if active:
        conn.close()
        return "Already Checked In"

    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")

    cursor.execute("SELECT full_name FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return "Student not found"

    full_name = student[0]

    cursor.execute("""
    INSERT INTO attendance
    (student_id, full_name, date, check_in, check_out, total_hours, status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (student_id, full_name, current_date, current_time, "", "0h 0m 0s", "Checked In"))

    attendance_id = cursor.lastrowid

    cursor.execute("""
    INSERT INTO attendance_events
    (attendance_id, student_id, full_name, date, time, action, total_hours)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (attendance_id, student_id, full_name, current_date, current_time, "Check In", "0h 0m 0s"))

    conn.commit()
    conn.close()
    return "Checked In"


def check_out_student(student_id):
    """
    Close the currently opened attendance session from the Check Out button in User.py.
    """
    conn = connect_db()
    cursor = conn.cursor()

    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")

    cursor.execute("SELECT full_name FROM students WHERE id = ?", (student_id,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return "Student not found"

    full_name = student[0]

    cursor.execute("""
    SELECT id, date, check_in
    FROM attendance
    WHERE student_id = ?
      AND status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    ORDER BY id DESC
    LIMIT 1
    """, (student_id,))

    open_record = cursor.fetchone()

    if not open_record:
        conn.close()
        return "No Active Check In"

    attendance_id, check_in_date, check_in_time = open_record

    check_in_datetime = datetime.strptime(
        f"{check_in_date} {check_in_time}",
        "%Y-%m-%d %H:%M:%S"
    )
    check_out_datetime = datetime.strptime(
        f"{current_date} {current_time}",
        "%Y-%m-%d %H:%M:%S"
    )

    total_seconds = (check_out_datetime - check_in_datetime).total_seconds()
    total_time = format_seconds(total_seconds)

    cursor.execute("""
    UPDATE attendance
    SET check_out = ?, total_hours = ?, status = ?
    WHERE id = ?
    """, (current_time, total_time, "Checked Out", attendance_id))

    cursor.execute("""
    INSERT INTO attendance_events
    (attendance_id, student_id, full_name, date, time, action, total_hours)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (attendance_id, student_id, full_name, current_date, current_time, "Check Out", total_time))

    conn.commit()
    conn.close()
    return "Checked Out"


def mark_attendance(student_id):
    """
    Backward-compatible name. Face login now only performs check-in.
    Check-out is done from the button inside User.py.
    """
    return check_in_student(student_id)

def get_attendance(student_id=None):
    conn = connect_db()
    cursor = conn.cursor()

    if student_id in (None, "", "All Students"):
        cursor.execute("""
        SELECT student_id, full_name, date, check_in, check_out, total_hours, status
        FROM attendance
        ORDER BY date DESC, id DESC
        """)
    else:
        cursor.execute("""
        SELECT student_id, full_name, date, check_in, check_out, total_hours, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY date DESC, id DESC
        """, (student_id,))

    records = cursor.fetchall()
    conn.close()
    return records



def get_active_attendance(student_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT date, check_in
    FROM attendance
    WHERE student_id = ?
      AND status = 'Checked In'
      AND (check_out IS NULL OR check_out = '')
    ORDER BY id DESC
    LIMIT 1
    """, (student_id,))

    active = cursor.fetchone()
    conn.close()
    return active


def get_user_attendance(student_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT date, check_in, check_out, total_hours, status
    FROM attendance
    WHERE student_id = ?
    ORDER BY date DESC, id DESC
    """, (student_id,))

    records = cursor.fetchall()
    conn.close()
    return records


def get_user_total_hours(student_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT total_hours FROM attendance WHERE student_id = ?", (student_id,))
    records = cursor.fetchall()
    conn.close()

    total_seconds = sum(parse_total_hours(record[0]) for record in records)
    return format_seconds(total_seconds)


def get_user_total_hours_minutes(student_id):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("SELECT total_hours FROM attendance WHERE student_id = ?", (student_id,))
    records = cursor.fetchall()
    conn.close()

    total_seconds = sum(parse_total_hours(record[0]) for record in records)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def add_attendance(student_id, full_name, date, time, status):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO attendance
    (student_id, full_name, date, check_in, check_out, total_hours, status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (student_id, full_name, date, time, "", "0h 0m 0s", status))

    attendance_id = cursor.lastrowid
    cursor.execute("""
    INSERT INTO attendance_events
    (attendance_id, student_id, full_name, date, time, action, total_hours)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (attendance_id, student_id, full_name, date, time, "Check In", "0h 0m 0s"))

    conn.commit()
    conn.close()


create_tables()
