ERP ATTENDANCE MODULE - ACTUAL STUDENT LIST VERSION

The Excel file supplied by the teacher is included as:
student list.xlsx

The Excel contains 75 student records.
Columns used:
- S#
- Enrolno
- Name

The application imports these students automatically when app.py starts.

SECTION:
K

TEACHER LOGIN
Username: teacher1
Password: teacher123

STUDENT LOGIN
Username: any enrollment number from the Excel file
Password: student123

Example:
Username: 200601
Password: student123

SETUP
1. Open this folder in VS Code.
2. Open Terminal -> New Terminal.
3. Run:
   python --version

4. Create virtual environment:
   python -m venv venv

5. Activate:
   venv\Scripts\activate

6. Install packages:
   pip install -r requirements.txt

7. Run:
   python app.py

8. Open:
   http://127.0.0.1:5000

DEMO FLOW
Teacher login
-> Dashboard
-> All 75 students appear
-> Mark / Update Attendance
-> Select subject and date
-> Mark Present / Absent
-> Save Attendance
-> Backend calculates percentage
-> If attendance < 75%, notification is generated
-> Logout
-> Student login
-> Student sees own attendance and notification

IMPORTANT:
Keep "student list.xlsx" in the SAME folder as app.py.
Do not rename it.

The first student in the Excel list is preloaded with a demo attendance pattern
of 70% in AI303 so the notification can be shown immediately.


NEW: ABSENCE NOTIFICATION + OPTIONAL CHANNELS
---------------------------------------------
When a teacher saves attendance, the app creates an in-app notification if a
student has just changed to Absent for that course/date. Re-saving the same
Absent record does not create another absence alert. The existing below-75%
attendance alert remains.

The app now has optional channel code in notification_service.py:
- Email: Gmail SMTP (requires a Gmail App Password and student email address).
- WhatsApp: Meta WhatsApp Cloud API (requires API credentials, recipient setup/opt-in,
  and possibly an approved template depending on the message type).
- SMS: simulation by default (printed to the terminal; NOT a real text message).
  Real SMS can optionally be configured with Twilio credentials, but trial/real
  messages may have charges and recipient restrictions.

IMPORTANT: The supplied Excel file only has enrollment number and name. It does
not contain student email addresses or phone numbers, so external messages will
be skipped until valid contact details are added to the users table. Do not add
real student contact details to a public/shared file.

To install the new dependency, activate your venv and run:
    pip install -r requirements.txt

Email setup (optional):
1. Turn on 2-Step Verification for your Gmail account.
2. Create an App Password in Google Account security settings.
3. In the same Command Prompt terminal where you will run the app, set:
    set SMTP_EMAIL=your_test_gmail@gmail.com
    set SMTP_APP_PASSWORD=your_16_character_app_password
4. Restart the app using:
    python app.py

Do not put your Gmail password or App Password directly in app.py, and do not
send credentials in chat. The variables set with Windows "set" apply only to
that terminal session.

WhatsApp setup (optional):
Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID using the values from
your Meta developer app / WhatsApp Cloud API test setup. Follow Meta's current
test-recipient and template requirements. Keep tokens private.

SMS:
The default is free simulation only. To attempt real SMS through Twilio, set:
    set SMS_PROVIDER=twilio
    set TWILIO_ACCOUNT_SID=your_account_sid
    set TWILIO_AUTH_TOKEN=your_auth_token
    set TWILIO_FROM_NUMBER=your_twilio_number
This is optional and may not be free for real recipients.

To add a student's contact details, first use test contact details you control.
The database columns are users.email and users.phone. The app automatically
adds these columns to an existing attendance.db on startup. Contact fields are
not yet editable through the portal UI.


EXTERNAL NOTIFICATIONS SETUP
1. Install packages using: python -m pip install -r requirements.txt
2. Copy .env.example to a file named .env and fill in your own credentials.
3. Never share or upload .env. It contains secrets.
4. Sign in as teacher and open Student Contact Details to save your own test email/phone.
5. Email uses Gmail SMTP App Password (2-Step Verification required).
6. WhatsApp uses Meta Cloud API. For messages initiated by the business, use an approved template; free-form text works only inside the customer-service window.
7. SMS uses Twilio API when configured. Trial restrictions and fees/India delivery eligibility may apply.
8. Attendance notifications still appear in the portal even if an external channel fails.


ASSIGNMENT REMINDER MODULE
--------------------------
1. Log in as teacher (teacher1 / teacher123).
2. Open "Assignments & Reminders" from the sidebar or teacher dashboard.
3. Enter an assignment title, select the subject, and set its due date.
4. When the due date is exactly 5 days away, the next time a student opens
   the Student Portal, an Assignment Reminder is added to their notifications.
5. The reminder stays in the student's portal notifications and appears again
   whenever the student opens or refreshes the portal. Refreshing does not create
   duplicate reminder records for the same assignment and student.
6. This reminder currently appears inside the portal. It does not send a separate
   email, WhatsApp, or SMS for assignments.

The assignment list and reminders are stored in attendance.db. The database
tables assignments and assignment_reminders are created automatically on startup.
