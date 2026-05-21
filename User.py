import sys
from datetime import datetime

import customtkinter as ctk

from database import (
    check_out_student,
    get_active_attendance,
    get_student_by_id,
    get_user_attendance,
    get_user_total_hours,
    get_user_total_hours_minutes,
    format_seconds,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_BG = "#0F172A"
SIDEBAR = "#1E293B"
CARD = "#111827"
SUCCESS = "#059669"
TEXT_MUTED = "#CBD5E1"
WARNING = "#F59E0B"


def load_records():
    records = get_user_attendance(student_id)
    total_hours = get_user_total_hours(student_id)
    total_hours_minutes = get_user_total_hours_minutes(student_id)

    total_label.configure(text=f"Total Time: {total_hours_minutes}")
    total_details_label.configure(text=f"Full total: {total_hours}")

    records_textbox.delete("1.0", "end")

    if not records:
        records_textbox.insert("end", "No attendance records found.")
        return

    for record in records:
        records_textbox.insert(
            "end",
            f"Date: {record[0]}\n"
            f"Check In: {record[1] or '-'}\n"
            f"Check Out: {record[2] or '-'}\n"
            f"Total Hours: {record[3] or '0h 0m 0s'}\n"
            f"Status: {record[4]}\n"
            f"{'-' * 45}\n"
        )


def check_out_now():
    result = check_out_student(student_id)

    if result == "Checked Out":
        checkout_button.configure(state="disabled", text="Checked Out")
        status_label.configure(text="Status: Checked Out", text_color=WARNING)
        live_timer_label.configure(text="0h 0m 0s", text_color=TEXT_MUTED)
        load_records()
        app.after(300, app.destroy)
    else:
        status_label.configure(text=f"Status: {result}", text_color=WARNING)
        load_records()


def update_live_timer():
    active = get_active_attendance(student_id)

    if active:
        date, check_in = active
        check_in_datetime = datetime.strptime(f"{date} {check_in}", "%Y-%m-%d %H:%M:%S")
        elapsed_seconds = (datetime.now() - check_in_datetime).total_seconds()
        live_timer_label.configure(text=format_seconds(elapsed_seconds), text_color=SUCCESS)
        status_label.configure(text=f"Status: Checked In since {check_in}", text_color=SUCCESS)
        checkout_button.configure(state="normal", text="Check Out")
    else:
        live_timer_label.configure(text="0h 0m 0s", text_color=TEXT_MUTED)
        status_label.configure(text="Status: Not checked in", text_color=WARNING)
        checkout_button.configure(state="disabled", text="No Active Check In")

    load_records()
    app.after(1000, update_live_timer)


if len(sys.argv) > 1:
    student_id = int(sys.argv[1])
else:
    student_id = 0

student = get_student_by_id(student_id)
student_name = student[1] if student else f"Student {student_id}"
student_email = student[2] if student else "Unknown"
department = student[3] if student else "Unknown"

app = ctk.CTk()
app.geometry("1050x650")
app.title("Student User Page")
app.configure(fg_color=APP_BG)

app.grid_columnconfigure(0, weight=0)
app.grid_columnconfigure(1, weight=1)
app.grid_rowconfigure(0, weight=1)

left_frame = ctk.CTkFrame(app, width=260, corner_radius=0, fg_color=SIDEBAR)
left_frame.grid(row=0, column=0, sticky="nsew")
left_frame.grid_propagate(False)

right_frame = ctk.CTkFrame(app, corner_radius=0, fg_color=APP_BG)
right_frame.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
right_frame.grid_columnconfigure(0, weight=1)
right_frame.grid_rowconfigure(3, weight=1)

ctk.CTkLabel(
    left_frame,
    text="Smart\nAttendance",
    font=("Arial", 30, "bold"),
    text_color="white",
    justify="left"
).pack(pady=(45, 20), padx=25, anchor="w")

ctk.CTkLabel(
    left_frame,
    text="Student Portal",
    font=("Arial", 18, "bold"),
    text_color=TEXT_MUTED
).pack(pady=10, padx=25, anchor="w")

ctk.CTkButton(
    left_frame,
    text="Refresh Records",
    width=210,
    height=42,
    corner_radius=12,
    command=load_records
).pack(pady=20, padx=25)

header_frame = ctk.CTkFrame(right_frame, corner_radius=18, fg_color=CARD, height=120)
header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 15))
header_frame.grid_propagate(False)

welcome_label = ctk.CTkLabel(
    header_frame,
    text=f"Welcome, {student_name}",
    font=("Arial", 32, "bold"),
    text_color="white"
)
welcome_label.place(relx=0.04, rely=0.22)

student_info_label = ctk.CTkLabel(
    header_frame,
    text=f"Student ID: {student_id}   |   Email: {student_email}   |   Department: {department}",
    font=("Arial", 16),
    text_color=TEXT_MUTED
)
student_info_label.place(relx=0.04, rely=0.62)

summary_frame = ctk.CTkFrame(right_frame, corner_radius=18, fg_color=CARD, height=165)
summary_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))
summary_frame.grid_propagate(False)
summary_frame.grid_columnconfigure((0, 1), weight=1)

live_card = ctk.CTkFrame(summary_frame, corner_radius=14, fg_color="#1F2937")
live_card.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
ctk.CTkLabel(live_card, text="Live Timer", font=("Arial", 17), text_color=TEXT_MUTED).pack(pady=(14, 4))
live_timer_label = ctk.CTkLabel(live_card, text="0h 0m 0s", font=("Arial", 28, "bold"), text_color=TEXT_MUTED)
live_timer_label.pack(pady=2)
status_label = ctk.CTkLabel(live_card, text="Status: Checking...", font=("Arial", 14), text_color=TEXT_MUTED)
status_label.pack(pady=2)

checkout_button = ctk.CTkButton(
    live_card,
    text="Check Out",
    height=34,
    fg_color="#DC2626",
    hover_color="#B91C1C",
    command=check_out_now
)
checkout_button.pack(pady=(6, 8), padx=20, fill="x")

total_card = ctk.CTkFrame(summary_frame, corner_radius=14, fg_color="#1F2937")
total_card.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
ctk.CTkLabel(total_card, text="Completed Total", font=("Arial", 17), text_color=TEXT_MUTED).pack(pady=(14, 4))
total_label = ctk.CTkLabel(total_card, text="Total Time: 0h 0m", font=("Arial", 28, "bold"))
total_label.pack(pady=2)
total_details_label = ctk.CTkLabel(total_card, text="Full total: 0h 0m 0s", font=("Arial", 14), text_color=TEXT_MUTED)
total_details_label.pack(pady=2)

records_frame = ctk.CTkFrame(right_frame, corner_radius=18, fg_color=CARD)
records_frame.grid(row=3, column=0, sticky="nsew")
records_frame.grid_columnconfigure(0, weight=1)
records_frame.grid_rowconfigure(1, weight=1)

ctk.CTkLabel(records_frame, text="My Attendance Records", font=("Arial", 24, "bold")).grid(
    row=0, column=0, sticky="w", padx=15, pady=15
)

records_textbox = ctk.CTkTextbox(records_frame, font=("Arial", 16))
records_textbox.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))

load_records()
update_live_timer()
app.mainloop()
