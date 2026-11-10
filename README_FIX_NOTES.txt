FIXED PROJECT COPY - ERP Attendance + Assignment + Fee Reminders

This copy is based on the ERP_Attendance_Assignment_Fee_Reminders project and keeps the existing attendance, assignment, and fee modules.

Fix included:
- Fee notification event logging now uses INSERT OR IGNORE and checks whether the event was newly inserted. Duplicate event keys no longer crash a portal page or create duplicate in-app notifications/emails.
- Python syntax compilation passed.
- Duplicate event behavior was tested with SQLite in-memory tables.

Before running:
1. Extract this ZIP.
2. Open the extracted ERP_Attendance_Actual_Student_List folder in VS Code.
3. Back up your current attendance.db before copying any data. This ZIP intentionally does not include your database or your private .env file.
4. Create .env from .env.example and enter your own Gmail SMTP settings if you want email alerts.
5. In the VS Code terminal, run:
   python -m venv venv
   venv\Scripts\activate
   python -m pip install -r requirements.txt
   python app.py
6. Open http://127.0.0.1:5000

If venv already exists, skip the venv creation command. Never share your .env file or Gmail App Password.
