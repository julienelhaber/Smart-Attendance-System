import csv
import os
import shutil
import subprocess
import sys
from logging import disable
from tkinter import filedialog, messagebox

import customtkinter as ctk

from Functions import save_student
from database import (
    check_out_attendance_session,
    delete_student,
    get_active_attendance_sessions,
    get_active_checkins_count,
    get_attendance,
    get_attendance_events,
    get_students,
    get_deleted_students,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_BG = "#0F172A"
SIDEBAR = "#1E293B"
CARD = "#111827"
ACCENT = "#2563EB"
SUCCESS = "#059669"
DANGER = "#DC2626"
TEXT_MUTED = "#CBD5E1"


# ======================= HELPERS =======================

def student_option_text(student):
    return f"{student[0]} - {student[1]}"


def get_selected_student_id(option_value):
    if not option_value or option_value == "All Students":
        return None
    return int(option_value.split(" - ")[0])


def refresh_student_menus():
    students = get_students()
    student_values = [student_option_text(student) for student in students]
    export_values = ["All Students"] + student_values

    delete_student_menu.configure(values=student_values if student_values else ["No Students"])
    export_student_menu.configure(values=export_values)

    if student_values:
        delete_student_menu.set(student_values[0])
    else:
        delete_student_menu.set("No Students")

    export_student_menu.set("All Students")

    if "active_session_menu" in globals():
        refresh_active_sessions_menu()

    load_dashboard()


def format_records(records):
    if not records:
        return "No attendance records found."

    text = ""
    for record in records:
        check_in_time = record[6] if len(record) > 6 and record[6] else "-"
        check_out_time = record[7] if len(record) > 7 and record[7] else "-"
        session_status = record[8] if len(record) > 8 and record[8] else "-"

        text += (
            f"Student ID: {record[0]}\n"
            f"Name: {record[1]}\n"
            f"Date: {record[2]}\n"
            f"Event Time: {record[3]}\n"
            f"Action: {record[4]}\n"
            f"Session Check In: {check_in_time}\n"
            f"Session Check Out: {check_out_time}\n"
            f"Session Status: {session_status}\n"
            f"Total Hours: {record[5] or '0h 0m 0s'}\n"
            f"{'-' * 45}\n"
        )
    return text


def set_readonly_text(textbox, content):
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")
    textbox.insert("end", content)
    textbox.configure(state="disabled")


def active_session_option_text(session):
    attendance_id, student_id, full_name, date, check_in, status = session
    return f"{attendance_id} - Student {student_id} - {full_name} - {date} {check_in}"


def get_selected_attendance_id(option_value):
    if not option_value or option_value == "No Active Sessions":
        return None
    return int(option_value.split(" - ")[0])


def format_active_sessions(records):
    if not records:
        return "No active check-in sessions found."

    text = ""
    for record in records:
        text += (
            f"Attendance Session ID: {record[0]}\n"
            f"Student ID: {record[1]}\n"
            f"Name: {record[2]}\n"
            f"Check-in Date: {record[3]}\n"
            f"Check-in Time: {record[4]}\n"
            f"Status: {record[5]}\n"
            f"{'-' * 45}\n"
        )
    return text


# ======================= BUTTON FUNCTIONS =======================

def load_dashboard():
    students = get_students()
    attendance_logs = get_attendance_events()
    active_checkins = get_active_checkins_count()

    total_students_label.configure(text=str(len(students)))
    total_logs_label.configure(text=str(len(attendance_logs)))
    active_checkins_label.configure(text=str(active_checkins))


def open_dashboard():
    tabs.set("Dashboard")
    load_dashboard()


def open_register():
    tabs.set("Register")


def open_students():
    tabs.set("Students")
    load_students()
    refresh_student_menus()


def open_logs():
    tabs.set("Attendance Logs")
    load_attendance_logs()
    refresh_student_menus()


def open_deleted_students():
    tabs.set("Deleted Students")
    load_deleted_students()


def open_active_sessions():
    tabs.set("Active Sessions")
    load_active_sessions()
    refresh_active_sessions_menu()


def load_students():
    students = get_students()

    if not students:
        set_readonly_text(students_textbox, "No registered students found.")
        return

    text = ""
    for student in students:
        text += (
            f"ID: {student[0]}\n"
            f"Name: {student[1]}\n"
            f"Email: {student[2]}\n"
            f"Department: {student[3]}\n"
            f"{'-' * 45}\n"
        )

    set_readonly_text(students_textbox, text)



def load_deleted_students():
    deleted_students = get_deleted_students()

    if not deleted_students:
        set_readonly_text(deleted_textbox, "No deleted students found.")
        return

    text = ""
    for student in deleted_students:
        text += (
            f"ID: {student[0]}\n"
            f"Name: {student[1]}\n"
            f"Email: {student[2]}\n"
            f"Department: {student[3]}\n"
            f"Deleted Date: {student[4]}\n"
            f"Deleted Time: {student[5]}\n"
            f"{'-' * 45}\n"
        )

    set_readonly_text(deleted_textbox, text)



def refresh_active_sessions_menu():
    sessions = get_active_attendance_sessions()
    session_values = [active_session_option_text(session) for session in sessions]

    active_session_menu.configure(values=session_values if session_values else ["No Active Sessions"])

    if session_values:
        active_session_menu.set(session_values[0])
    else:
        active_session_menu.set("No Active Sessions")


def load_active_sessions():
    sessions = get_active_attendance_sessions()
    set_readonly_text(active_sessions_textbox, format_active_sessions(sessions))
    refresh_active_sessions_menu()
    load_dashboard()


def admin_check_out_selected_session():
    selected = active_session_menu.get()
    attendance_id = get_selected_attendance_id(selected)

    if attendance_id is None:
        messagebox.showwarning("No Active Sessions", "No active student session is selected.")
        return

    answer = messagebox.askyesno(
        "Manual Check Out",
        "Check out this active student session manually?"
    )

    if not answer:
        return

    result = check_out_attendance_session(attendance_id)

    if result == "Checked Out":
        messagebox.showinfo("Checked Out", "The selected student session was checked out successfully.")
    else:
        messagebox.showwarning("Not Checked Out", result)

    load_active_sessions()
    load_attendance_logs()


def delete_selected_student():
    selected = delete_student_menu.get()

    if selected == "No Students":
        messagebox.showwarning("No Students", "No registered students found.")
        return

    student_id = get_selected_student_id(selected)
    answer = messagebox.askyesno(
        "Delete Student",
        "Delete this student account? Attendance logs will stay saved."
    )

    if not answer:
        return

    deleted = delete_student(student_id)

    if deleted:
        dataset_folder = os.path.join("dataset", str(student_id))
        if os.path.exists(dataset_folder):
            shutil.rmtree(dataset_folder)

        # Retrain model immediately so deleted students are removed from recognition data.
        if os.path.exists("Train.py") and os.path.exists("dataset") and os.listdir("dataset"):
            subprocess.run([sys.executable, "Train.py"], check=False)
        elif os.path.exists("trainer.yml"):
            os.remove("trainer.yml")

        messagebox.showinfo("Deleted", "Student deleted successfully. Attendance logs were kept.")
        load_students()
        load_deleted_students()
        refresh_student_menus()
    else:
        messagebox.showerror("Error", "Student was not found.")


def load_attendance_logs():
    selected = export_student_menu.get() if "export_student_menu" in globals() else "All Students"
    student_id = get_selected_student_id(selected)
    records = get_attendance_events(student_id)

    set_readonly_text(attendance_logs_textbox, format_records(records))


def export_logs():
    selected = export_student_menu.get()
    student_id = get_selected_student_id(selected)
    records = get_attendance_events(student_id)

    if not records:
        messagebox.showwarning("No Data", "No attendance records found for this filter.")
        return

    filename = "attendance_logs.csv" if student_id is None else f"student_{student_id}_attendance_logs.csv"
    file_path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        initialfile=filename,
        filetypes=[("CSV files", "*.csv")]
    )

    if not file_path:
        return

    with open(file_path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Student ID",
            "Full Name",
            "Date",
            "Event Time",
            "Action",
            "Total Hours",
            "Session Check In",
            "Session Check Out",
            "Session Status"
        ])
        writer.writerows(records)

    messagebox.showinfo("Export Complete", f"Logs exported successfully:\n{file_path}")


def save_student_and_refresh():
    save_student(name_entry, email_entry, department_menu)
    refresh_student_menus()
    load_students()


def capture_face_images():
    # In this version saving a student also captures the 20 face images.
    save_student_and_refresh()


# ======================= WINDOW =======================

app = ctk.CTk()
app.geometry("1200x700")
app.title("Smart Attendance System")
app.configure(fg_color=APP_BG)

app.grid_rowconfigure(0, weight=1)
app.grid_columnconfigure(0, weight=0)
app.grid_columnconfigure(1, weight=1)

left_frame = ctk.CTkFrame(app, corner_radius=0, fg_color=SIDEBAR, width=280)
left_frame.grid(row=0, column=0, sticky="nsew")
left_frame.grid_propagate(False)

right_frame = ctk.CTkFrame(app, corner_radius=0, fg_color=APP_BG)
right_frame.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
right_frame.grid_rowconfigure(1, weight=1)
right_frame.grid_columnconfigure(0, weight=1)

top_right_frame = ctk.CTkFrame(right_frame, corner_radius=18, fg_color=CARD, height=95)
top_right_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
top_right_frame.grid_propagate(False)

bottom_right_frame = ctk.CTkFrame(right_frame, corner_radius=18, fg_color=CARD)
bottom_right_frame.grid(row=1, column=0, sticky="nsew")
bottom_right_frame.grid_rowconfigure(0, weight=1)
bottom_right_frame.grid_columnconfigure(0, weight=1)

# ======================= SIDEBAR =======================

title_label = ctk.CTkLabel(
    left_frame,
    text="Smart\nAttendance",
    font=("Arial", 30, "bold"),
    text_color="white",
    justify="left"
)
title_label.pack(pady=(35, 25), padx=25, anchor="w")

button_style = {
    "width": 230,
    "height": 42,
    "font": ("Arial", 15, "bold"),
    "corner_radius": 12,
    "anchor": "w"
}

ctk.CTkButton(left_frame, text="Dashboard", command=open_dashboard, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="Register Student", command=open_register, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="View / Delete Students", command=open_students, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="Deleted Students", command=open_deleted_students, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="Active Sessions", command=open_active_sessions, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="Attendance Logs", command=open_logs, **button_style).pack(pady=8, padx=20)
ctk.CTkButton(left_frame, text="Export Logs", command=open_logs, fg_color=SUCCESS, hover_color="#047857", **button_style).pack(pady=8, padx=20)

# ======================= HEADER =======================

title_text = ctk.CTkLabel(
    top_right_frame,
    text="Smart Attendance Admin Dashboard",
    font=("Arial", 34, "bold"),
    text_color="white"
)
title_text.place(relx=0.04, rely=0.28)

# ======================= TABS =======================

tabs = ctk.CTkTabview(bottom_right_frame, fg_color=CARD, segmented_button_selected_color=ACCENT)
tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

tabs.add("Dashboard")
tabs.add("Register")
tabs.add("Students")
tabs.add("Deleted Students")
tabs.add("Active Sessions")
tabs.add("Attendance Logs")

# ======================= DASHBOARD TAB =======================

dashboard_tab = tabs.tab("Dashboard")
dashboard_tab.grid_columnconfigure((0, 1, 2), weight=1)
dashboard_tab.grid_rowconfigure(1, weight=1)

ctk.CTkLabel(dashboard_tab, text="System Overview", font=("Arial", 26, "bold")).grid(
    row=0, column=0, columnspan=3, sticky="w", padx=15, pady=15
)

cards = []
for col, title in enumerate(["Total Students", "Attendance Logs", "Currently Checked In"]):
    card = ctk.CTkFrame(dashboard_tab, corner_radius=16, fg_color="#1F2937")
    card.grid(row=1, column=col, sticky="nsew", padx=15, pady=15)
    ctk.CTkLabel(card, text=title, font=("Arial", 18), text_color=TEXT_MUTED).pack(pady=(35, 10))
    value = ctk.CTkLabel(card, text="0", font=("Arial", 42, "bold"))
    value.pack(pady=10)
    cards.append(value)

total_students_label, total_logs_label, active_checkins_label = cards

# ======================= REGISTER TAB =======================

register_tab = tabs.tab("Register")
register_tab.grid_columnconfigure(0, weight=1)
register_tab.grid_columnconfigure(1, weight=2)

ctk.CTkLabel(register_tab, text="Register New Student", font=("Arial", 26, "bold")).grid(
    sticky="w", padx=15, pady=15, row=0, column=0, columnspan=2
)

ctk.CTkLabel(register_tab, text="Full Name", font=("Arial", 18)).grid(sticky="w", padx=15, pady=15, row=1, column=0)
name_entry = ctk.CTkEntry(register_tab, placeholder_text="Enter student full name", height=42)
name_entry.grid(sticky="ew", padx=15, pady=15, row=1, column=1)

ctk.CTkLabel(register_tab, text="Student Email", font=("Arial", 18)).grid(sticky="w", padx=15, pady=15, row=2, column=0)
email_entry = ctk.CTkEntry(register_tab, placeholder_text="Enter student email", height=42)
email_entry.grid(sticky="ew", padx=15, pady=15, row=2, column=1)

ctk.CTkLabel(register_tab, text="Department", font=("Arial", 18)).grid(sticky="w", padx=15, pady=15, row=3, column=0)
department_menu = ctk.CTkOptionMenu(register_tab, values=["CS", "IT", "AI", "CyberSecurity"], height=42)
department_menu.grid(sticky="ew", padx=15, pady=15, row=3, column=1)

ctk.CTkLabel(register_tab, text="Face Images", font=("Arial", 18)).grid(sticky="w", padx=15, pady=15, row=4, column=0)
faceimage_entry = ctk.CTkEntry(register_tab, placeholder_text="Images will be captured automatically", height=42, state="disabled")
faceimage_entry.grid(sticky="ew", padx=15, pady=15, row=4, column=1)

ctk.CTkButton(register_tab, text="Capture Face + Save Student", height=42, fg_color=SUCCESS, hover_color="#047857", command=capture_face_images).grid(
    sticky="ew", padx=15, pady=25, row=5, column=0, columnspan=2
)


# ======================= STUDENTS TAB =======================

students_tab = tabs.tab("Students")
students_tab.grid_columnconfigure(0, weight=1)
students_tab.grid_rowconfigure(2, weight=1)

ctk.CTkLabel(students_tab, text="Registered Students", font=("Arial", 26, "bold")).grid(
    row=0, column=0, padx=15, pady=15, sticky="w"
)

student_actions_frame = ctk.CTkFrame(students_tab, fg_color="#1F2937", corner_radius=14)
student_actions_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
student_actions_frame.grid_columnconfigure(0, weight=1)

delete_student_menu = ctk.CTkOptionMenu(student_actions_frame, values=["No Students"], height=40)
delete_student_menu.grid(row=0, column=0, padx=12, pady=12, sticky="ew")
ctk.CTkButton(
    student_actions_frame,
    text="Delete Selected Student",
    height=40,
    fg_color=DANGER,
    hover_color="#B91C1C",
    command=delete_selected_student
).grid(row=0, column=1, padx=12, pady=12)
ctk.CTkButton(student_actions_frame, text="Refresh", height=40, command=open_students).grid(row=0, column=2, padx=12, pady=12)

students_textbox = ctk.CTkTextbox(students_tab, font=("Arial", 16), state="disabled")
students_textbox.grid(row=2, column=0, padx=15, pady=15, sticky="nsew")

# ======================= DELETED STUDENTS TAB =======================

deleted_students_tab = tabs.tab("Deleted Students")
deleted_students_tab.grid_columnconfigure(0, weight=1)
deleted_students_tab.grid_rowconfigure(1, weight=1)

ctk.CTkLabel(deleted_students_tab, text="Deleted Students Archive", font=("Arial", 26, "bold")).grid(
    row=0, column=0, padx=15, pady=15, sticky="w"
)

deleted_textbox = ctk.CTkTextbox(deleted_students_tab, font=("Arial", 16), state="disabled")
deleted_textbox.grid(row=1, column=0, padx=15, pady=15, sticky="nsew")

ctk.CTkButton(
    deleted_students_tab,
    text="Refresh Deleted Students",
    height=40,
    command=load_deleted_students
).grid(row=2, column=0, padx=15, pady=(0, 15), sticky="ew")

# ======================= ACTIVE SESSIONS TAB =======================

active_sessions_tab = tabs.tab("Active Sessions")
active_sessions_tab.grid_columnconfigure(0, weight=1)
active_sessions_tab.grid_rowconfigure(2, weight=1)

ctk.CTkLabel(active_sessions_tab, text="Active Student Sessions", font=("Arial", 26, "bold")).grid(
    row=0, column=0, padx=15, pady=15, sticky="w"
)

active_sessions_actions_frame = ctk.CTkFrame(active_sessions_tab, fg_color="#1F2937", corner_radius=14)
active_sessions_actions_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
active_sessions_actions_frame.grid_columnconfigure(0, weight=1)

active_session_menu = ctk.CTkOptionMenu(active_sessions_actions_frame, values=["No Active Sessions"], height=40)
active_session_menu.grid(row=0, column=0, padx=12, pady=12, sticky="ew")

ctk.CTkButton(
    active_sessions_actions_frame,
    text="Manual Check Out",
    height=40,
    fg_color=DANGER,
    hover_color="#B91C1C",
    command=admin_check_out_selected_session
).grid(row=0, column=1, padx=12, pady=12)

ctk.CTkButton(active_sessions_actions_frame, text="Refresh", height=40, command=load_active_sessions).grid(
    row=0, column=2, padx=12, pady=12
)

active_sessions_textbox = ctk.CTkTextbox(active_sessions_tab, font=("Arial", 16), state="disabled")
active_sessions_textbox.grid(row=2, column=0, padx=15, pady=15, sticky="nsew")

# ======================= ATTENDANCE LOGS / EXPORT TAB =======================

attendance_logs_tab = tabs.tab("Attendance Logs")
attendance_logs_tab.grid_columnconfigure(0, weight=1)
attendance_logs_tab.grid_rowconfigure(2, weight=1)

ctk.CTkLabel(attendance_logs_tab, text="Attendance Logs Export", font=("Arial", 26, "bold")).grid(
    row=0, column=0, padx=15, pady=15, sticky="w"
)

export_filter_frame = ctk.CTkFrame(attendance_logs_tab, fg_color="#1F2937", corner_radius=14)
export_filter_frame.grid(row=1, column=0, sticky="ew", padx=15, pady=10)
export_filter_frame.grid_columnconfigure(1, weight=1)

ctk.CTkLabel(export_filter_frame, text="Filter Student:", font=("Arial", 16)).grid(row=0, column=0, padx=12, pady=12)
export_student_menu = ctk.CTkOptionMenu(export_filter_frame, values=["All Students"], height=40, command=lambda value: load_attendance_logs())
export_student_menu.grid(row=0, column=1, padx=12, pady=12, sticky="ew")
ctk.CTkButton(export_filter_frame, text="Load Logs", height=40, command=load_attendance_logs).grid(row=0, column=2, padx=12, pady=12)
ctk.CTkButton(export_filter_frame, text="Export CSV", height=40, fg_color=SUCCESS, hover_color="#047857", command=export_logs).grid(row=0, column=3, padx=12, pady=12)

attendance_logs_textbox = ctk.CTkTextbox(attendance_logs_tab, font=("Arial", 16), state="disabled")
attendance_logs_textbox.grid(row=2, column=0, padx=15, pady=15, sticky="nsew")

refresh_student_menus()
load_students()
load_deleted_students()
load_active_sessions()
load_attendance_logs()
tabs.set("Dashboard")

app.mainloop()
